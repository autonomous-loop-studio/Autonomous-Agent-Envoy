# models/

Drop your `.gguf` files in this folder.

Agent Envoy scans `models/` next to `envoy.py` first, then `../models`, then `~/models`. It takes
every `.gguf` it finds there (smallest file first) and the `m` key cycles through them.

**Recommended model:** [MBHudson/ALS-MYTHOS-4B-heretic-f16](https://huggingface.co/MBHudson/ALS-MYTHOS-4B-heretic-f16) — 4B, F16, ~8.4 GB, fine-tuned for this addon.

```bash
pip install -U huggingface_hub
hf download MBHudson/ALS-MYTHOS-4B-heretic-f16 ALS-MYTHOS-4B-heretic-f16.gguf --local-dir models
```

Any `.gguf` works, and it does not have to live here: set `"model"` in `config.json` to an absolute
path anywhere on disk.

`.gguf` files are gitignored — never commit them.
