# テンプレdocxの各段落について、見出し（太字）と改行はそのままに本文だけを差し替える。
import io, re, sys, zipfile
from xml.sax.saxutils import escape

tpl, md_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
md = io.open(md_path, encoding="utf-8").read()

def sec(name):
    m = re.search(re.escape("## 【" + name + "】") + r"\n\n(.+?)(?=\n\n##|\Z)", md, re.S)
    return m.group(1).strip().replace("\n", "")

order = ["演題名", "目的", "方法", "結果", "結論"]
zin = zipfile.ZipFile(tpl)
x = zin.read("word/document.xml").decode("utf-8")
paras = re.findall(r"<w:p[ >].*?</w:p>", x, re.S)
SZ = '<w:sz w:val="28"/><w:szCs w:val="28"/>'
done = []
for p in paras:
    txt = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
    m = re.match(r"【([^】]+)】", txt)
    if not m or m.group(1) not in order:
        continue
    name = m.group(1)
    open_tag = re.match(r"<w:p[^>]*>", p).group(0)
    ppr = re.search(r"<w:pPr>.*?</w:pPr>", p, re.S).group(0)
    new = (open_tag + ppr
           + f'<w:r><w:rPr><w:rStyle w:val="ac"/>{SZ}</w:rPr><w:t>【{name}】</w:t></w:r>'
           + f'<w:r><w:rPr>{SZ}</w:rPr><w:br/></w:r>'
           + f'<w:r><w:rPr><w:rFonts w:hint="eastAsia"/>{SZ}</w:rPr>'
           + f'<w:t xml:space="preserve">{escape(sec(name))}</w:t></w:r></w:p>')
    x = x.replace(p, new, 1)
    done.append(name)
assert done == order, done
zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
for item in zin.infolist():
    data = x.encode("utf-8") if item.filename == "word/document.xml" else zin.read(item.filename)
    zout.writestr(item, data)
zout.close()
print("written", out, done)
