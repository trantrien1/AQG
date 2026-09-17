// Đếm công thức KaTeX không dựng được trong từng bản ghi.
// node katex_check.js in.jsonl  ->  mỗi dòng {"key": ..., "bad": n, "first_error": ...}
// Bản ghi vào: {"key", "question", "choices": [...], "solution"}
const fs = require('fs');
const katex = require('katex');

const lines = fs.readFileSync(process.argv[2], 'utf8').split('\n').filter(Boolean);
for (const line of lines) {
  const rec = JSON.parse(line);
  const fields = [rec.question || '', rec.solution || '', ...(rec.choices || [])];
  let bad = 0;
  let firstError = null;
  for (const text of fields) {
    const re = /\$([^$]*)\$/g;
    let m;
    while ((m = re.exec(text))) {
      try {
        katex.renderToString(m[1], { throwOnError: true, strict: 'ignore' });
      } catch (e) {
        bad += 1;
        if (!firstError) firstError = e.message.slice(0, 120);
      }
    }
  }
  console.log(JSON.stringify({ key: rec.key, bad, first_error: firstError }));
}
