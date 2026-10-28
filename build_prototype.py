"""Build the self-contained offline prototype; no external packages required."""
from pathlib import Path
import base64
import json

ROOT = Path(__file__).resolve().parent
source = ROOT / "prototype"
(source / 'news-sources.js').write_text('/* Public source catalog; generated from news/sources.json. */\nwindow.StillNewsSources = ' + json.dumps(json.loads((ROOT / 'news/sources.json').read_text()), indent=2) + ';\n')
html = (source / "index.html").read_text()
css = (source / "style.css").read_text()
font = base64.b64encode((source / 'assets/public-sans.ttf').read_bytes()).decode()
css = css.replace("url('assets/public-sans.ttf')", "url('data:font/ttf;base64," + font + "')")
html = html.replace('<link rel="stylesheet" href="style.css">', '<style>\n' + css + '\n</style>')
for name in ['model.js', 'data.js', 'gate.js', 'boot.js', 'assets/charts.js', 'news-sources.js', 'news.js', 'settings.js', 'companies.js', 'app.js']:
    html = html.replace('<script src="' + name + '"></script>', '<script>\n' + (source / name).read_text() + '\n</script>')
licenses = '\n\n'.join((source / 'assets' / name).read_text() for name in ['LICENSE-taste-skill.txt', 'OFL-public-sans.txt'])
html = html.replace('</head>', '<!-- Bundled component licenses:\n' + licenses + '\n-->\n</head>')
output = ROOT / "artifacts" / "still-prototype.html"
output.parent.mkdir(exist_ok=True)
html = '\n'.join(line.rstrip() for line in html.splitlines()) + '\n'
output.write_text(html)
(ROOT / 'dist').mkdir(exist_ok=True)
(ROOT / 'dist' / 'index.html').write_text(html)
print(f"Built {output} ({output.stat().st_size:,} bytes)")
