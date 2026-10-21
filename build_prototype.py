"""Build the self-contained offline prototype; no external packages required."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
source = ROOT / "prototype"
html = (source / "index.html").read_text()
html = html.replace('<link rel="stylesheet" href="style.css">', '<style>\n' + (source / "style.css").read_text() + '\n</style>')
html = html.replace('<script src="app.js"></script>', '<script>\n' + (source / "app.js").read_text() + '\n</script>')
output = ROOT / "artifacts" / "still-prototype.html"
output.parent.mkdir(exist_ok=True)
output.write_text(html)
(ROOT / 'dist').mkdir(exist_ok=True)
(ROOT / 'dist' / 'index.html').write_text(html)
print(f"Built {output} ({output.stat().st_size:,} bytes)")
