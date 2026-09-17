// Kiểm tra mọi công thức $...$ trong file JSONL đều dựng được bằng KaTeX.
//   npm install katex@0.16
//   node dataset/tools/check_latex.js dataset/export/questions.jsonl
const fs = require('fs');
const katex = require('katex');

const lines = fs.readFileSync(process.argv[2], 'utf8').trim().split('\n');
let spans = 0;
const bad = [];
for (const line of lines) {
  const it = JSON.parse(line);
  const fields = [['question', it.question], ['solution', it.solution],
    ...it.choices.map((c, i) => [`choices[${i}]`, c])];
  for (const [field, text] of fields) {
    if (((text.match(/\$/g) || []).length) % 2) {
      bad.push({ id: it.id, field, error: 'số dấu $ lẻ' });
    }
    for (const m of text.matchAll(/\$([^$]*)\$/g)) {
      spans += 1;
      try {
        katex.renderToString(m[1], { throwOnError: true, strict: 'ignore' });
      } catch (e) {
        bad.push({ id: it.id, field, latex: m[1].slice(0, 100), error: e.message.slice(0, 100) });
      }
    }
  }
}
console.log(`${lines.length} câu, ${spans} công thức, ${bad.length} lỗi`);
for (const b of bad.slice(0, 50)) console.log(JSON.stringify(b));
process.exit(bad.length ? 1 : 0);
