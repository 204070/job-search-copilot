# artifacts/ — your private documents

Everything in this folder is **gitignored**: your resume, cover letters and
any other personal files stay on your machine. The only committed files here
are this README and the `*.example.md` placeholders — so clone this repo,
drop your documents in with the standard names below, and never worry about
pushing them.

## Standard names

Scripts and workflows expect these filenames:

| File | What goes there |
|---|---|
| `resume.md` | Your resume — source material for keyword scoring and application scripts |
| `cover-letter.md` | Your base cover letter (other variants: `cover-letter.<variant>.md`) |
| `profile.jsonc` | Personal facts for form filling (name, email, phone, location, links, work-auth answers, targeting, positioning) — private, read before filling any application |
| `scripts/` | Helper scripts for the semi-auto workflow (e.g. `embed_resume.sh` — chunked base64 resume upload into Greenhouse pages) |
| `generated/` | Machine-built files (e.g. generated resume PDFs) — superseded by hand-tuned originals unless noted |
| `faqs/` | **Generated** interview/application Q&A (`application-faq.md`, `technical-faq.md`) — rendered from the question bank by `python3 -m db.tools.questions digest`; edit the bank with `record`, not these files |

Get started by copying the placeholders:

```bash
cp artifacts/resume.example.md artifacts/resume.md
cp artifacts/cover-letter.example.md artifacts/cover-letter.md
```

Anything else personal (interview notes, references, salary history) can live
here too — the whole directory is ignored.

**Not stored here:** daily lead reports are runtime logs and go to
`logs/leads/` (also gitignored, free to rotate or delete).
