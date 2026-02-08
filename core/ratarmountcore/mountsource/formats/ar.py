import contextlib
import io
import logging
import os
import re
import stat
import struct
import tarfile
import threading
from pathlib import Path
from typing import IO, Optional, Union, cast

from ratarmountcore.mountsource import FileInfo, MountSource
from ratarmountcore.mountsource.SQLiteIndexMountSource import SQLiteIndexMountSource
from ratarmountcore.SQLiteIndex import SQLiteIndex
from ratarmountcore.StenciledFile import RawStenciledFile, StenciledFile
from ratarmountcore.utils import RatarmountError, overrides

logger = logging.getLogger(__name__)


def _parse_ar_archive(fileObject: IO[bytes]) -> list[tarfile.TarInfo]:
    """Parse the AR archive and return SQLiteIndex rows."""
    # To make this reusable, it would make more sense to return a tarfile.TarInfo struct.
    # TODO This would allow integration into SQLiteIndexedTar. But, instead of integrating it there,
    #      it would be cleaner to extract the compression layer undoing out of SQLiteIndexedTar,
    #      generalize it to work with arbitrarily stacked compressions.
    #      Then, SQLiteIndexedTar, ASARMountSource, ARMountSource, and other non-compressed archive formats,
    #      such as ISO, and possibly ZIP, might be refactored into a base class that implements the file lock
    #      and the stenciled file opening using the file offset and size in the underlying archive.
    magic = fileObject.read(8)
    is_thin = magic == b'!<thin>\n'
    if magic != b'!<arch>\n' and not is_thin:
        raise RatarmountError(f"Invalid AR magic bytes: {magic!r}")

    offset = fileObject.tell()

    _DECIMAL_NUMBER_REGEX = re.compile(b"[0-9]* *")

    def parse_int(field_bytes, base=10, default=0):
        # https://www.unix.com/man-page/opensolaris/3head/ar.h/
        # > All information in the file member headers is in printable ASCII.
        #
        # https://man.freebsd.org/cgi/man.cgi?query=ar&sektion=5&manpath=4.3BSD+NET%2F2
        # > Any unused characters in any of these fields are written as space characters.
        # > If any fields are their particular maximum number of characters in length,
        # > there will be no separation between the fields.
        #
        # Note that "int()" already ignores leading and trailing spaces and works with bytes.
        # https://docs.python.org/3/library/functions.html#int
        # > If the argument is not a number or if base is given, then it must be a string, bytes,
        # > or bytearray instance representing an integer in radix base.
        # > Optionally, the string can be [...] be surrounded by whitespace
        if not _DECIMAL_NUMBER_REGEX.fullmatch(field_bytes):
            raise ValueError("Expected integer encoded as string padded with spaces, but got: %s", field_bytes)
        field_str = field_bytes.strip()  # Strip to test whether it contains any valid digits.
        return int(field_str, base) if field_str else default

    files: list[tarfile.TarInfo] = []

    # Offset | Length | Content                                  | Format
    # -------+--------+------------------------------------------+--------
    # 0      | 16     | File identifier                          | ASCII
    # 16     | 12     | File modification timestamp (in seconds) | Decimal
    # 28     |  6     | Owner ID                                 | Decimal
    # 34     |  6     | Group ID                                 | Decimal
    # 40     |  8     | File mode (type and permission)          | Octal
    # 48     | 10     | File size in bytes                       | Decimal
    # 58     |  2     | Ending characters                        | 0x60 0x0A
    # https://en.wikipedia.org/wiki/Ar_(Unix)
    HEADER_SIZE = 60
    POSIX_SYMBOL_TABLE_NAME = b'/'
    GNU_INDEX_NAME = b'//'
    BSD_LONG_NAME_PREFIX = b'#1/'
    # For thin archives, it simply is bytes because for some reason thin archives use byte indexes while
    # normal archives index by file name entry.
    long_names: Optional[Union[bytes, list[bytes]]] = None

    # It could be argued that the special 'debian-binary' text file could be ignored because it should be
    # interpreted as some kind of magic bytes, but I am not fully convinced of that. Simply also display
    # that file and no special consideration for "DEB-support" is required.

    def get_long_file_name(name: bytes):
        if long_names and name.startswith(b'/') and name[1:].isdigit():
            index = int(name[1:])
            if index >= 0 and index < len(long_names):
                if not is_thin:
                    return long_names[index]

                if isinstance(long_names, bytes):  # Should always be the case for is_thin.
                    end = long_names.find(b'/\n', index)
                    if end >= index:
                        return long_names[index:end]
        return name

    while header_data := fileObject.read(HEADER_SIZE):
        if len(header_data) < HEADER_SIZE:
            raise RatarmountError(f"Encountered incomplete AR header: {header_data!r}")

        offset = fileObject.tell()
        tar_info = tarfile.TarInfo()
        tar_info.offset = offset - HEADER_SIZE
        tar_info.offset_data = offset

        try:
            header_parts = struct.unpack("16s12s6s6s8s10s2s", header_data)
            if header_parts[-1] != b'`\n':
                raise RatarmountError(f"Invalid AR file header ending characters ({header_parts[-1]})!")

            name = header_parts[0].rstrip(b' \x00')

            # fmt: off
            tar_info.mtime = parse_int(header_parts[1], 10)
            tar_info.uid   = parse_int(header_parts[2], 10)
            tar_info.gid   = parse_int(header_parts[3], 10)
            tar_info.mode  = parse_int(header_parts[4], 8, 0o660) | stat.S_IFREG  # AR has no folder support
            tar_info.size  = parse_int(header_parts[5], 10)
            # fmt: on

            if is_thin:
                tar_info.mode |= stat.S_IFLNK

        except (ValueError, struct.error) as exception:
            logger.warning(
                "Failed to parse AR header at offset %s because of: %s",
                offset,
                exception,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
            logger.debug("Header data: %s", header_data)
            raise RatarmountError("Invalid AR archive!") from exception

        size = tar_info.size  # Includes the BSD long name for correct even-byte padding.

        if name == POSIX_SYMBOL_TABLE_NAME:
            # Ignore the symbol table for now.
            fileObject.seek(size + size % 2, io.SEEK_CUR)
            continue

        if name == GNU_INDEX_NAME:
            if is_thin:
                long_names = fileObject.read(size)
            else:
                long_names = fileObject.read(size).split(b'/\n')

                # GNU ar pads the table internally to an even size.
                if size % 2 == 0:
                    if long_names and long_names[-1] in (b'\x60', b'\x0a'):
                        long_names.pop()
                else:
                    fileObject.seek(size % 2, io.SEEK_CUR)  # Skip padding

            # Retroactively apply the index if it is not the very first entry in the archive.
            for file in files:
                if is_thin:
                    file.linkname = get_long_file_name(file.name)  # type: ignore
                else:
                    file.name = get_long_file_name(file.name)  # type: ignore

            continue

        if name.startswith(BSD_LONG_NAME_PREFIX):
            # https://man.freebsd.org/cgi/man.cgi?query=ar&sektion=5&manpath=4.3BSD+NET%2F2
            # > If any file name is more than 16 characters in length or contains an embedded space,
            # > the string "#1/" followed by the ASCII length of the name is written in the name field.
            # > The file size (stored in the archive header) is incremented by the length of the name.
            # > The name is then written immediately following the archive header.
            name_size = int(name[len(BSD_LONG_NAME_PREFIX) :])
            name = fileObject.read(name_size)
            if len(name) != name_size:
                raise RatarmountError(f"Read insufficient data for BSD long file name ({name_size}): {name!r}")
            tar_info.offset_data += name_size
            tar_info.size -= name_size

        if long_names:
            if is_thin:
                tar_info.linkname = get_long_file_name(name)
                tar_info.type = tarfile.SYMTYPE
            else:
                name = get_long_file_name(name)

        # Archives created with llvm-ar-19 -r --format=bsd add random null-byte padding even though
        # padding should not be necessary because the name size can be specified exactly via BSD_LONG_NAME_PREFIX.
        tar_info.name = name.strip(b'\0')
        files.append(tar_info)

        if is_thin:
            fileObject.seek(offset)
            continue

        # Skip padding: https://www.unix.com/man-page/opensolaris/3head/ar.h/
        # > Each archive file member begins on an even byte boundary; a newline is inserted between files if necessary.
        # > Nevertheless, the size given reflects the actual size of the file exclusive of padding.
        fileObject.seek(offset + size + (size % 2))

    return files


# TODO Very similar to ASARMountSource. There might be more potential for refactoring to minimize code duplication.
class ARMountSource(SQLiteIndexMountSource):
    def __init__(self, fileOrPath: Union[str, IO[bytes], Path], **options) -> None:
        if isinstance(fileOrPath, Path):
            fileOrPath = str(fileOrPath)
        self.isFileObject = not isinstance(fileOrPath, str)
        self.fileObject = open(fileOrPath, 'rb') if isinstance(fileOrPath, str) else fileOrPath

        indexOptions = {
            'archiveFilePath': fileOrPath if isinstance(fileOrPath, str) else None,
            'backendName': 'ARMountSource',
        }
        super().__init__(**(options | indexOptions))

        # Try to get block size from the real opened file.
        self.blockSize = 512
        with contextlib.suppress(Exception):
            self.blockSize = os.fstat(self.fileObject.fileno()).st_blksize

        self.fileObjectLock = threading.Lock()

        self._finalize_index(
            lambda: self.index.set_file_infos(
                [self._convert_to_row(info) for info in _parse_ar_archive(self.fileObject)]
            )
        )

    def _convert_to_row(self, info: tarfile.TarInfo) -> tuple:
        mode = info.mode
        if mode == 0:
            mode = 0o770 if info.isdir() else 0o660
        mode = mode | (stat.S_IFLNK if info.issym() else mode) | (stat.S_IFDIR if info.isdir() else stat.S_IFREG)

        name = info.name.decode(self.index.encoding)  # type: ignore
        path, name = SQLiteIndex.normpath(self.transform(name)).rsplit("/", 1)

        linkname = info.linkname.decode(self.index.encoding) if isinstance(info.linkname, bytes) else info.linkname

        # fmt: off
        fileInfo : tuple = (
            path            ,  # 0  : path
            name            ,  # 1  : file name
            info.offset     ,  # 2  : header offset
            info.offset_data,  # 3  : data offset
            info.size       ,  # 4  : file size
            info.mtime      ,  # 5  : modification time
            mode            ,  # 6  : file mode / permissions
            0               ,  # 7  : TAR file type. Currently unused.
            linkname        ,  # 8  : linkname
            info.uid        ,  # 9  : user ID
            info.gid        ,  # 10 : group ID
            False           ,  # 11 : is TAR (unused?)
            False           ,  # 12 : is sparse
            False           ,  # 13 : is generated (parent folder)
            0               ,  # 14 : recursion depth
        )
        # fmt: on

        return fileInfo

    def _open_stencil(self, offset: int, size: int, buffering: int) -> IO[bytes]:
        if buffering == 0:
            return cast(IO[bytes], RawStenciledFile([(self.fileObject, offset, size)], self.fileObjectLock))
        return cast(
            IO[bytes],
            StenciledFile(
                [(self.fileObject, offset, size)],
                self.fileObjectLock,
                bufferSize=self.blockSize if buffering == -1 else buffering,
            ),
        )

    @overrides(MountSource)
    def open(self, fileInfo: FileInfo, buffering=-1) -> IO[bytes]:
        if stat.S_ISLNK(fileInfo.mode):
            raise RatarmountError("Cannot read contents of symbolic link!")
        return self._open_stencil(SQLiteIndex.get_index_userdata(fileInfo.userdata).offset, fileInfo.size, buffering)
