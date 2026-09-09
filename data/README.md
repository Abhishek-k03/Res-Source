# Your corpus

Drop research material here, in any mix of folders. `python scripts/ingest.py files`
walks this directory recursively and indexes everything it recognises:

| Extension | Read with |
| --- | --- |
| `.pdf` | pypdf, one document per page |
| `.md`, `.markdown`, `.txt` | read directly as UTF-8 |
| `.html`, `.htm` | BeautifulSoup, text only |

Anything else is skipped, and a file that fails to parse is logged and skipped
rather than aborting the run.

The contents of this folder are gitignored, so your papers stay out of version
control. This file is the exception, which also means a fresh clone has one
document to index as a smoke test.
