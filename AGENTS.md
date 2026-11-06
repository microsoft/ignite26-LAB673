# Agent instructions

## Skillable instructions tips

[instructions/skillable.md](instructions/skillable.md) is the lab sidebar that Skillable shows next to the lab VM. Skillable's Markdown differs from GitHub's, so follow these rules when editing it:

- **Pages:** separate sidebar pages with a line containing only `===`. End each page with a line such as "Select **Next** to continue to …".
- **No backticks:** Skillable turns inline code into type-text blocks. Use **bold** for things attendees find on screen (UI labels, index and resource names, JSON sections, XML element names) and *italics* for field names and values (*chunk*, *Batch*, *madeFrom*). Use quotes for short phrases that aren't on screen.
- **Type-text:** wrap anything attendees should type or paste in `+++…+++`, such as search queries, URLs, and commands. Skillable adds a click-to-type button. Skillable tokens such as `@lab.CloudPortalCredential(User1).Username` also go inside `+++…+++`.
- **No links to repository files:** Skillable rewrites relative links to blob storage URLs that don't open the file on the VM. Tell attendees to open the file in Visual Studio Code by its path from the repository root, such as **data/graph-data/cocoarynth.owl**. Links to external sites such as Microsoft Learn are fine.
- **Windows paths and commands:** the lab VM runs Windows, so use paths like `.venv\Scripts\python.exe src\explorer\app.py` in commands.
- **Keep detail in the notebooks:** the sidebar says what to do and what to notice. Leave explanations of how things work, such as how ontologies are attached to knowledge sources, to the notebooks.
- **Terminology:** say "Foundry IQ" (not Azure AI Search), "chunk" (not passage), and "Foundry IQ plugin" for the tool that pre-processed the data.
- **Section endings:** each part ends with a "🍫 Food for thought" section of one or two short reflection questions.
- **Skillable keeps its own copies:** after changing the sidebar or a lifecycle script in [infra/](infra/), paste the new version into the Skillable lab profile too.
