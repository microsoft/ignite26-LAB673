@lab.Title
## Before you begin

<details>
<summary><strong>🔑 Lab credentials (click to expand when you need to sign in)</strong></summary>

At any point during the lab, if you need to sign in to the virtual machine (Windows) or any Azure or Microsoft 365 apps (M365 Copilot, SharePoint, Teams, and so on), use the credentials provided below.

### Sign into virtual machine (Windows)

If you need to sign in the virtual machine, use the following credentials:

- **User name**: +++@lab.VirtualMachine(Win11-Pro-Base).Username+++  
- **Password**: +++@lab.VirtualMachine(Win11-Pro-Base).Password+++

### Sign into Azure & Microsoft 365

If you need to sign in to any Azure or Microsoft 365 apps, use the following credentials:

- **Username**: +++@lab.CloudPortalCredential(User1).Username+++  
- **Temporary Access Pass**: +++@lab.CloudPortalCredential(User1).AccessToken+++

</details>

## Overview

In this hands-on lab, you'll explore Foundry IQ knowledge bases for Cocoarynth Chocolate Works, a fictional bean-to-bar chocolate maker. Its records are scattered across farm logs, factory tests, shipping paperwork, retailer emails, and company policies.

You'll work through three notebooks:

1. **Knowledge bases and Microsoft Retriever 1 (MR1)**: Ask a grounded question over four filtered document sources in one chunk index, follow the citations, and compare standard agentic retrieval with the faster MR1 retriever.
2. **Entities and graphs**: Follow a chocolate batch back to the farms that grew its cacao, using an ontology, graph queries, and provenance.
3. **Topics**: Browse labeled groups of passages, compare topic routing with direct vector search, and query the sitemap with GQL and a graph-enabled knowledge source.

## Sign into Windows

In the virtual machine, sign into Windows using the following credentials:

- **User name**: +++@lab.VirtualMachine(Win11-Pro-Base).Username+++  
- **Password**: +++@lab.VirtualMachine(Win11-Pro-Base).Password+++

## Open the project folder in Visual Studio Code

The lab repository is already cloned on your desktop in the **Desktop > ignite26-LAB673** folder. It contains all the code, notebooks, and data you'll need.

1. Open Visual Studio Code.
2. Select **File > Open Folder**.
3. Navigate to **Desktop**, select the **ignite26-LAB673** folder, and then select **Select Folder**.

> [!TIP]
>
> When prompted whether to trust the authors of the files, select **Yes, I trust the authors**.

## Verify environment variables

All required Azure services have already been provisioned for you.

<details>
<summary><strong>📋 What's pre-configured (click to expand for details)</strong></summary>

- **Foundry IQ** with three pre-created indexes:
  - **cocoarynth-topics**: Topic vectors, labels, descriptions, memberships, and sitemap relationships
  - **cocoarynth-chunks**: 106 passages from the 55 original PDFs, with embeddings and a `domain` field for origins, quality, logistics-retail, and policies
  - **cocoarynth-graph**: PDF-supported business triples constrained by the checked-in OWL ontology
- **Graph-enabled knowledge sources** for the business graph and topic sitemap, using the November inline-ontology private preview
- **Checked-in OWL files**: Ontologies are files, not additional indexes
- **Azure OpenAI** with **gpt-5.4** for query planning and answer synthesis, and **text-embedding-3-large** for vector embeddings
- **Pre-computed vectors**: All Cocoarynth document chunks are already vectorized and indexed

</details>

1. Open the **.env** file in the main project folder.
2. Verify that it includes these environment variables:
   - *AZURE_SEARCH_SERVICE_ENDPOINT*
   - *AZURE_SEARCH_ADMIN_KEY*
   - *AZURE_OPENAI_ENDPOINT*
   - *AZURE_OPENAI_KEY*
   - *AZURE_OPENAI_CHATGPT_DEPLOYMENT*
   - *AZURE_OPENAI_CHATGPT_MODEL_NAME*

## Sign into the Azure portal

You'll use the Azure portal throughout the lab to inspect your Foundry IQ service.

1. Open a web browser and navigate to +++https://portal.azure.com+++.
2. Sign in using your lab credentials:
    - **Username**: +++@lab.CloudPortalCredential(User1).Username+++  
    - **Temporary Access Pass**: +++@lab.CloudPortalCredential(User1).AccessToken+++
3. In the search bar at the top, search for +++@lab.CloudResourceGroup(Lab673-ResourceGroup).Name+++ and open your lab resource group.
4. Select your Foundry IQ service (its name starts with *lab673-search-*). Keep this tab open.

Select **Next** to start exploring the indexes.

===

# Part 1: Knowledge bases and Microsoft Retriever 1

In this part, you'll look at the search indexes in the Azure portal, then use a notebook to build a knowledge base over them and ask a grounded question. Finally, you'll return to the portal to see the knowledge base you created.

## Explore the indexes in the Azure portal

1. In your Foundry IQ service, select **Search management** > **Indexes** from the left pane.
2. Confirm that you see these three indexes, each with a nonzero document count:
   - **cocoarynth-topics**
   - **cocoarynth-chunks**
   - **cocoarynth-graph**
3. Select **cocoarynth-chunks** to open it in **Search explorer**.
4. Enter +++organic seal+++ in the search box and select **Search**. Each result is a PDF passage with *title*, *blob_path*, and *domain* fields. Policy passages have *domain* set to *policies*.
5. In the same index, search for +++EC26-0811+++. This is a chocolate batch code that you'll trace back to its farms in Part 2.
6. Select the **Fields** tab to see how the index is structured. Notice the *chunk* text field and the vector field that holds its embedding.

## Run the Python notebook

1. In Visual Studio Code, open **src/notebooks/lab/01-knowledge-base-and-mr1.ipynb**.
2. Run each cell in order. When prompted to select a kernel, select **Python Environments** and then **.venv**.
3. Follow the instructions in the notebook.

## See your knowledge base in the Azure portal

1. Return to your Foundry IQ service in the Azure portal.
2. From the left pane, select **Agentic retrieval** > **Knowledge sources**. Find the four document knowledge sources that the notebook created, such as **cocoarynth-origins-source**. They all target **cocoarynth-chunks**, with different *domain* filters. The two graph-enabled sources were created during setup.
3. Select **Agentic retrieval** > **Knowledge bases**. Open the **cocoarynth-kb-standard** knowledge base.
4. Look at which knowledge sources it uses, which chat completion model it uses for query planning and answer synthesis, and its retrieval reasoning effort.
5. Open the **cocoarynth-kb-mr1** knowledge base too. Notice that it uses only the policies source.

Select **Next** to continue to entities and graphs.

===

# Part 2: Entities and graphs

A Pantry Lane customer has a chocolate wrapper with batch code **EC26-0811** and wants to know which farms grew its cacao. A single passage can mention a batch or a farm, but a graph makes the connection explicit: **Batch → BeanLot ← Farm**.

The Azure portal doesn't show graphs yet, so this lab includes a small web app, the **Cocoarynth graph explorer**, for looking at the graph visually.

## Start the graph explorer

1. In Visual Studio Code, select **Terminal** > **New Terminal**.
2. Run this command to start the app:

    +++.venv\Scripts\python.exe src\explorer\app.py+++

3. The app opens in your browser at +++http://localhost:8765+++. If it doesn't, open that address yourself. Keep the terminal running for the rest of the lab.

## Explore the ontology

The **Ontology** tab shows the graph's schema. Each circle is an entity type, and each arrow is a relationship from its domain (subject type) to its range (object type).

1. In Visual Studio Code, open **data/graph-data/cocoarynth.owl**. This checked-in file defines the entity types and properties; there is no ontology index. The explorer reads this file, and setup attaches its declarations inline to the graph knowledge source.
2. Return to the explorer and select the **BeanLot** circle. The panel lists the relationships to and from a bean lot.
3. In the panel, select **Batch → madeFrom** and then **Farm → contributedTo**. These two relationships connect a batch to the farms that grew its beans.

## Explore the graph

1. Select the **Graph** tab. It opens with batch **EC26-0811** and the entities directly connected to it.
2. Look at the batch-code property and the **madeFrom** relationship. The compact graph contains selected facts, not every detail in the documents.
3. Select the **EC26-L07** bean lot circle to add its neighbors to the diagram. Find the two farms that contributed to it.
4. Select a **contributedTo** arrow, or select it in the panel's list of relationships. The panel shows the assertion, exact evidence excerpts, and the original PDF passage it came from.
5. Compare the farm names with [the cooperative's collection tickets](../data/cocoarynth/documents/cocoarynth-origins/boletas-acopio-rio-claro-2026.pdf). The structured JSON used to generate the PDFs is not graph evidence.

## Run the notebook

Now do the same exploration with code, and compare it with a knowledge base.

1. In Visual Studio Code, open **src/notebooks/lab/02-entities-and-graphs.ipynb**.
2. Run each cell in order, using the same **.venv** kernel.
3. Follow the instructions in the notebook. You'll:
   - Read the checked-in OWL ontology, which defines entity types such as *Batch*, *BeanLot*, and *Farm* and the relationships between them.
   - Open batch record EC26-0811 and compare it with the stored graph assertion.
   - Write a GQL query that follows the batch to its bean lot and then to the farms.
   - Follow the result's provenance back to the source evidence.
   - Ask the same question through a graph-backed knowledge base and through the standard knowledge base from Part 1, then compare them.

## Check your understanding

- What's the difference between the ontology and the graph's individual entities?
- In the answer from the graph-backed knowledge base, can you find a successful *graphSearch* activity and a graph citation?
- Did the standard knowledge base also answer correctly? What does the graph make easier to inspect?

Select **Next** to continue to topics.

===

# Part 3: Topics

An entity graph shows how specific things are connected. Topics group related passages so you can explore a broader area of the documents.

## Explore topics in the graph explorer

1. In the graph explorer, select the **Topics** tab. If you closed the app, start it again as described in Part 2.
2. Look at the coverage in the panel. Not every passage was assigned to a topic.
3. Broad topics are on the left, and narrower child topics are on the right. Each box has a label added from its member passages; select it to read the description. There are four roots and four children, and two roots have no children.
4. Select a topic to read its member passages. Do they have something in common? Labels describe the fixed groups; they do not change which passages belong to a topic.

## Run the notebook

1. In Visual Studio Code, open **src/notebooks/lab/03-topics.ipynb**.
2. Run each cell in order, using the same **.venv** kernel.
3. Follow the instructions in the notebook. You'll:
   - Check how much of the document set the topics cover.
   - Browse the topic hierarchy and its member passages.
   - Pick a passage about Madagascar bean lot MG26-L02 and find its nearest neighbors in two ways: directly, and through its nearest topic.
   - Query **Topic → subtopic → member passage ← PDF document** with GQL on **cocoarynth-topics**.
   - Use **cocoarynth-topics-ks** from a knowledge base, then look for a successful, nonempty *graphSearch* activity. A text-only answer does not demonstrate sitemap GQL.

## Check your understanding

Think about the three questions from this lab: the organic seal, the farms behind batch EC26-0811, and a broad topic browse. Which retrieval approach would you start with for each one, and why?

Select **Next** to review key takeaways and next steps.

===

# Summary

You've completed the lab on exploring Foundry IQ knowledge bases. You:

- Built a knowledge base over four filtered sources in one PDF chunk index, followed its citations back to the original documents, and compared it with the faster Microsoft Retriever 1.
- Followed a chocolate batch to its farms with an ontology, GQL queries, and graph provenance, and compared a graph-backed knowledge base with standard retrieval.
- Explored labeled topic groups, compared topic-based search with direct vector search, and queried the sitemap through GQL and its inline-ontology knowledge source.

| Need | Good starting point |
| --- | --- |
| Ground a direct question in original passages | Standard knowledge base |
| Respond quickly when the app already knows which source to use | Microsoft Retriever 1 (MR1) |
| Follow explicit relationships across records | Entity graph and GQL |
| Explore groups of related passages and navigate their sitemap | Topics and sitemap GQL |

## Continue learning

- [Foundry IQ](https://learn.microsoft.com/azure/search/) - Explore the full capabilities of Foundry IQ and how it integrates with other Microsoft Foundry and Azure services.
- [Design an index for agentic retrieval in Foundry IQ](https://learn.microsoft.com/azure/search/search-agentic-retrieval-how-to-index) - Best practices for structuring your data for agentic retrieval.
- [Create a knowledge base in Foundry IQ](https://learn.microsoft.com/azure/search/search-agentic-retrieval-how-to-create?tabs=rbac%2Cpython-get-agents%2Cpython-create-agent%2Cpython-query-agent%2Cpython-delete-agent) - Step-by-step guide to creating and configuring knowledge bases.
- [Create a knowledge source](https://learn.microsoft.com/azure/search/search-knowledge-source-overview) - Understand how to create and configure different data sources.
- [Use answer synthesis for citation-backed responses in Foundry IQ](https://learn.microsoft.com/azure/search/search-agentic-retrieval-how-to-synthesize) - Learn how to generate grounded answers with citations using answer synthesis.

## Next steps

Here are some ways to apply what you've learned:

**Customize retrieval behavior** - Adjust reasoning effort levels, and configure custom retrieval and answer instructions for specific sources.

**Integrate with your data** - Replace the sample Cocoarynth indexes with your own enterprise content.

**Build a conversational interface** - Connect the knowledge base to an agent with additional tools and a chat UI for end users.
