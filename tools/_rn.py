import io
p = 'README.md'
s = io.open(p, encoding='utf-8').read()
s = s.replace('\\\\', '\\')
lines = s.split('\n')
for i in range(len(lines) - 1):
    if lines[i].startswith('| `data') and lines[i].endswith('|') and lines[i + 1].strip() == '---':
        lines.insert(i + 1, '')
        break
s = '\n'.join(lines)
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print('NORM_OK')