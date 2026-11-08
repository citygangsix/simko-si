# Granite response → Everyday English

Return path for `everyday_to_granite.py`. Heuristic only. No second model. The same sentences apply when `PODCODER_COMPUTE` is `local` or `cloud`.

```bash
python3 granite_to_everyday.py --response reply.html \
  --feature mul --ask "add multiply" -o /tmp/everyday.txt
```

Stdout is plain English, not JSON.

- HTML becomes a short calculator line, for example: `Multiplication is in. Click 7, *, 8, = — you should see 56.`
- Empty, timeout, or FAIL becomes: `Granite didn't finish / failed this step — … Try again or use Aider once.`
- Aider chatter becomes: `Made a small fix: …`
- Other prose is compressed to one or two sentences. Raw HTML is never pasted into the everyday line.

The chat UI shows that line first. Raw model output stays behind “Show raw model output.” Mission status stores `everyday_line` the same way.
