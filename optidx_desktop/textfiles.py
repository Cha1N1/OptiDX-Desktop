"""Small configuration-file edits preserve BOM, endian and newline conventions."""

import codecs


def encode_edited(original, text):
    bom, encoding = b"", "utf-8"
    for marker, codec in [
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
        (codecs.BOM_UTF8, "utf-8"),
    ]:
        if original.startswith(marker):
            bom, encoding = marker, codec
            break
    before = original[len(bom) :].decode(encoding)
    newline = "\r\n" if "\r\n" in before else "\r" if "\r" in before else "\n"
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    return bom + text.encode(encoding)
