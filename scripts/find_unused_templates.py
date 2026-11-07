"""One-off audit: printable templates never rendered by any route."""
import glob
import pathlib
import re

routed = set()
for p in glob.glob('routes/**/*.py', recursive=True) + glob.glob('services/**/*.py', recursive=True) + glob.glob('models/**/*.py', recursive=True) + glob.glob('utils/**/*.py', recursive=True) + glob.glob('app.py'):
    text = pathlib.Path(p).read_text(encoding='utf-8')
    routed.update(re.findall(r"render_template\(['\"]([^'\"]+)['\"]", text))
    # include-pattern references ({% include 'x.html' %})
    routed.update(re.findall(r"['\"]([A-Za-z0-9_./-]+\.html)['\"]", text))

for p in pathlib.Path('templates').rglob('*.html'):
    routed.update(re.findall(r'<include[^>]*template=[\"\']([^\"\']+)[\"\']', pathlib.Path(p).read_text(encoding='utf-8')))

incl = set()
for p in pathlib.Path('templates').rglob('*.html'):
    incl.update(re.findall(r"['\"]\s*include\s+['\"]([^'\"]+)['\"]", pathlib.Path(p).read_text(encoding='utf-8')))
    incl.update(re.findall(r"include\s+['\"]([^'\"]+)['\"]", pathlib.Path(p).read_text(encoding='utf-8')))
routed |= incl

all_t = {str(p.relative_to('templates')).replace('\\', '/') for p in pathlib.Path('templates').rglob('*.html')}
unused = sorted(all_t - routed)
print('UNUSED TEMPLATES (no route/js render_template match):')
for t in unused:
    print(' ', t)
print('count:', len(unused), 'total:', len(all_t))
