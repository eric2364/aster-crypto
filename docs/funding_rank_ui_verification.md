# Funding-rank report display verification

6 October 2026. The actual published report was opened in the in-app browser.
Five Plotly charts rendered, the five account results and fifteen gates matched
the audited exports, and no browser console errors were reported. At the normal
desktop viewport (1,570 CSS pixels), the document width was 1,545 pixels.
The captured preview is [here](funding-rank-preview.png).

A temporary narrow viewport was also inspected. Text and the result table
remained readable, with the table scrolling within its container; however,
Plotly content produced document-level horizontal overflow (650-pixel reported
viewport, 1,156-pixel document). Mobile layout is therefore not certified. The
normal desktop viewport was restored and the report left open for the user.
No sealed publication files or economic results were changed during this check.

Final complete test run: **1,024 passed in 51.01 seconds**.
