import io

import pypdfium2.raw as pdfium_c
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from pypdfium2 import PdfDocument

writer = PdfWriter()
nl = chr(10)
sb = ("0 0 72 144 re f" + nl).encode()
s = DecodedStreamObject()
s.set_data(sb)
writer.add_object(s)  # register as indirect object
ref = writer._objects[-1] if hasattr(writer, "_objects") else None
print("registered:", ref)
page = writer.add_blank_page(width=72, height=144)
page[NameObject("/Contents")] = ref
writer.add_page(page)
buf = io.BytesIO()
writer.write(buf)
data = buf.getvalue()
print(data.decode("latin1")[:500])

doc = PdfDocument(data)
pg = doc[0]
print("page objects:", list(pg.get_objects()))
bitmap = pg.render(scale=2.0)
pil = bitmap.to_pil()
nw = sum(1 for px in pil.getdata() if px != (255, 255, 255))
print("default render non-white:", nw)
bitmap.close()
pg.close()
doc.close()
