#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import stat
from typing import Dict, IO, Iterable, Optional, Union

from .MountSource import FileInfo, MountSource
from .utils import overrides

try:
    from pyfatfs.PyFatFS import PyFatFS, PyFatBytesIOFS
except ImportError:
    PyFatFS = None  # type: ignore
    PyFatBytesIOFS = None  # type: ignore


class FATMountSource(MountSource):
    def __init__(self, fileOrPath: Union[str, IO[bytes]], **options) -> None:
        fatOptions = {'read_only': True}
        self.fileSystem = (
            PyFatFS(fileOrPath, **fatOptions)
            if isinstance(fileOrPath, str)
            else PyFatBytesIOFS(fileOrPath, **fatOptions)
        )
        self.options = options
        print("list dir /:", self.fileSystem.listdir('/'))

    @staticmethod
    def _convertPyFilesystem2Info(info, path) -> FileInfo:
        """
        info: fs.info.Info object from the PyFilesystem2 wrapper begin used around PyFatFS.
        """
        mode = 0o555 | (stat.S_IFDIR if info.is_dir else stat.S_IFREG)

        return FileInfo(
            # fmt: off
            size     = info.size,
            mtime    = info.raw.get('details', {}).get('accessed', 0),
            mode     = mode,
            linkname = "",  # FAT has no support for hard or symbolic links
            uid      = os.getuid(),
            gid      = os.getgid(),
            userdata = [path],
            # fmt: on
        )

    @overrides(MountSource)
    def isImmutable(self) -> bool:
        return True

    @overrides(MountSource)
    def listDir(self, path: str) -> Optional[Union[Iterable[str], Dict[str, FileInfo]]]:
        if not self.fileSystem.exists(path):
            return None
        # TODO I think with the low-level API, we could also get the FileInfos
        return self.fileSystem.listdir(path)

    @overrides(MountSource)
    def listDirModeOnly(self, path: str) -> Optional[Union[Iterable[str], Dict[str, int]]]:
        if not self.fileSystem.exists(path):
            return None
        # TODO I think with the low-level API, we could also get the FileInfos
        return self.fileSystem.listdir(path)

    @overrides(MountSource)
    def getFileInfo(self, path: str, fileVersion: int = 0) -> Optional[FileInfo]:
        if not self.fileSystem.exists(path):
            return None
        return self._convertPyFilesystem2Info(self.fileSystem.getinfo(path), path)

    @overrides(MountSource)
    def fileVersions(self, path: str) -> int:
        return 1

    @overrides(MountSource)
    def open(self, fileInfo: FileInfo, buffering=-1) -> IO[bytes]:
        path = fileInfo.userdata[-1]
        assert isinstance(path, str)
        return self.fileSystem.open(path, 'rb', buffering=buffering)

    @overrides(MountSource)
    def __exit__(self, exception_type, exception_value, exception_traceback):
        self.fileSystem.close()
