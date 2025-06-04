import email
fname='saved-mail.eml'
from email.message import EmailMessage
from email.parser import Parser
from email.policy import default
from email.parser import BytesParser
with open(fname, 'rb') as fp:
    headers = BytesParser(policy=default).parse(fp)

list(headers)
# ['X-Account-Key', 'X-UIDL', 'X-Mozilla-Status', 'X-Mozilla-Status2', 'X-Mozilla-Keys', 'Received', 'Received', 'Content-Type', 'Subject', 'Content-Disposition', 'From', 'In-Reply-To', 'Date', 'CC', 'Content-Transfer-Encoding', 'Message-ID', 'References', 'To', 'X-Mailer', 'Return-Path', 'X-ClientProxiedBy', 'X-MS-Exchange-Organization-Network-Message-Id', 'X-MS-Exchange-Organization-Antispam-Report', 'X-MS-Exchange-Organization-SCL', 'X-MS-Exchange-Organization-AVStamp-Enterprise', 'X-PMWin-Version', 'X-MS-Exchange-Organization-AuthSource', 'X-MS-Exchange-Organization-AuthAs', 'MIME-Version']
fname2='pimht/tests/example_com.mhtml'
with open(fname2, 'rb') as fp:
    headers2 = BytesParser(policy=default).parse(fp)

list(headers2)
# ['From', 'Snapshot-Content-Location', 'Subject', 'Date', 'MIME-Version', 'Content-Type']
with open(fname, 'rb') as fp:
    msg = email.message_from_binary_file(fp, policy=default)

list(msg)
# ['X-Account-Key', 'X-UIDL', 'X-Mozilla-Status', 'X-Mozilla-Status2', 'X-Mozilla-Keys', 'Received', 'Received', 'Content-Type', 'Subject', 'Content-Disposition', 'From', 'In-Reply-To', 'Date', 'CC', 'Content-Transfer-Encoding', 'Message-ID', 'References', 'To', 'X-Mailer', 'Return-Path', 'X-ClientProxiedBy', 'X-MS-Exchange-Organization-Network-Message-Id', 'X-MS-Exchange-Organization-Antispam-Report', 'X-MS-Exchange-Organization-SCL', 'X-MS-Exchange-Organization-AVStamp-Enterprise', 'X-PMWin-Version', 'X-MS-Exchange-Organization-AuthSource', 'X-MS-Exchange-Organization-AuthAs', 'MIME-Version']
print([part.get_payload(decode=True) for part in msg.walk()])

with open(fname2, 'rb') as fp:
    msg2 = email.message_from_binary_file(fp, policy=default)

print([part.get_payload(decode=True) for part in msg2.walk()])
# [None, b'<!DOCTYPE html><html><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><link rel="stylesheet" type="text/css" href="cid:css-abe2e82c-a3e6-420f-bdcd-7c12e58a7e6a@mhtml.blink" />\n    <title>Example Domain</title>\n\n    \n    \n    <meta name="viewport" content="width=device-width, initial-scale=1">\n        \n</head>\n\n<body><div>\n    <h1>Example Domain</h1>\n    <p>This domain is for use in illustrative examples in documents. You may use this\n    domain in literature without prior coordination or asking for permission.</p>\n    <p><a href="https://www.iana.org/domains/example">More information...</a></p>\n</div></body></html>', b'@charset "utf-8";\n\nbody { background-color: rgb(240, 240, 242); margin: 0px; padding: 0px; font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", "Open Sans", "Helvetica Neue", Helvetica, Arial, sans-serif; }\n\ndiv { width: 600px; margin: 5em auto; padding: 2em; background-color: rgb(253, 253, 255); border-radius: 0.5em; box-shadow: rgba(0, 0, 0, 0.02) 2px 3px 7px 2px; }\n\na:link, a:visited { color: rgb(56, 72, 143); text-decoration: none; }\n\n@media (max-width: 700px) {\n  div { margin: 0px auto; width: auto; }\n}', b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x01\x00\x00\x00\x007n\xf9$\x00\x00\x00\nIDATx\x01c`\x00\x00\x00\x02\x00\x01su\x01\x18\x00\x00\x00\x00IEND\xaeB`\x82']

# See also:
#  - https://en.wikipedia.org/wiki/MHTML
#    > The .mhtml and .eml filename extensions are interchangeable: either filename extension can be changed
#    > from one to the other. An .eml message can be sent by e-mail, and it can be displayed by an email client.
#    > An email message can be saved using a .mhtml or .mht filename extension and then opened for display in a
#    > web browser or for editing other programs, including word processors and text editors.
#  - https://stackoverflow.com/questions/31250/content-type-for-mht-files
#  - https://datatracker.ietf.org/doc/html/rfc2557
#
#  - https://docs.python.org/3/library/email.examples.html
#  - https://docs.python.org/3/library/email.html#module-email
#  - https://github.com/pilate/pimht/blob/master/pimht/pimht.py
#    -> do not need this. works sufficiently with email module. I only need to get the respective keys.
#  - for mbox: https://docs.python.org/3/library/mailbox.html#module-mailbox
