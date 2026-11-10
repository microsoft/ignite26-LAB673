@lab.Title
## Before you begin

<details>
<summary><strong>🔑 Lab credentials (click to expand when you need to sign in)</strong></summary>

At any point during the lab, if you need to sign in to the virtual machine (Windows) or any Azure or Microsoft 365 apps (M365 Copilot, SharePoint, Teams, and so on), use the credentials provided below.

### Sign into virtual machine (Windows)

If you need to sign in to the virtual machine, use the following credentials:

- **User name**: +++@lab.VirtualMachine(ILL344:Win11).Username+++
- **Password**: +++@lab.VirtualMachine(ILL344:Win11).Password+++

### Sign into Azure & Microsoft 365

If you need to sign in to any Azure or Microsoft 365 apps, use the following credentials:

- **Username**: +++@lab.CloudPortalCredential(User1).Username+++
- **Temporary Access Pass**: +++@lab.CloudPortalCredential(User1).AccessToken+++

</details>

## Overview

In this hands-on lab, you'll explore Foundry IQ knowledge bases for Cocoarynth Chocolate Works, a fictional bean-to-bar chocolate maker. Its records are scattered across farm logs, factory tests, shipping paperwork, retailer emails, and company policies.

You'll work through three notebooks:

1. **Knowledge bases and Microsoft Retriever 1 (MR1)**: Ask a grounded question over three document indexes, follow the citations, and compare standard agentic retrieval with the faster MR1 retriever.
2. **Entities and graphs**: Follow a chocolate batch back to the farms that grew its cacao, using an ontology, graph queries, and provenance.
3. **Topics**: Browse labeled groups of chunks, look inside the topic graph with code and GQL to see how the chunks were grouped, and investigate a customer complaint with topics and PDF evidence.

## Sign into Windows

In the virtual machine, sign into Windows using the following credentials:

- **User name**: ++@lab.VirtualMachine(ILL344:Win11).Username++ 
- **Password**: +++@lab.VirtualMachine(ILL344:Win11).Password+++

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

- **Prepared data**: The lab includes 55 Cocoarynth PDFs and their chunks (pieces of text such as a section, a table, or a short page), embeddings, topics, and a PDF-supported entity graph with its ontology. Setup restores the prepared snapshots into the indexes below.
- **Foundry IQ** with six pre-created indexes:
  - **cocoarynth-production**, **cocoarynth-sales**, and **cocoarynth-policies**: The PDF chunks for each document group, with embeddings
  - **cocoarynth-chunks**: All 106 chunks from the 55 original PDFs in one index, used for business graph evidence and topic-centroid vector searches
  - **cocoarynth-graph**: PDF-supported business triples constrained by the checked-in OWL ontology
  - **cocoarynth-topics**: Topic titles, descriptions, hierarchy facts, proportions, and terminal-topic vectors
- **Graph-enabled knowledge sources** for the business graph and topic sitemap, using the November inline-ontology private preview
- **Checked-in OWL files**: The business ontology and the canonical topic navigation schema. They're files, not additional indexes
- **Azure OpenAI** with **gpt-6-luna** for query planning and answer synthesis, and **text-embedding-3-large** for vector embeddings

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

In this part, you'll look at the search indexes in the Azure portal, then use a notebook to build a knowledge base over the three document indexes, ask it a grounded question, and compare standard agentic retrieval with Microsoft Retriever 1 (MR1). Finally, you'll return to the portal to see the knowledge sources and knowledge bases you created.

## Explore the indexes in the Azure portal

1. In your Foundry IQ service, select **Search management** > **Indexes** from the left pane.
2. You should see six indexes, each with a nonzero document count. Part 1 uses these three, which store the PDF chunks for each document group:
   - **cocoarynth-production**: farm and harvest records through factory batch records
   - **cocoarynth-sales**: shipping, retailers, and customers
   - **cocoarynth-policies**: company policies

   You'll also see **cocoarynth-chunks**, **cocoarynth-graph**, and **cocoarynth-topics**. You'll use those later.
3. Select **cocoarynth-policies** to open it in **Search explorer**.
4. Enter +++organic seal+++ in the search box and select **Search**. The results are JSON, with two main parts:
   - **@search.answers** comes first. The semantic ranker picked short extracts that it thinks directly answer the query. Each answer's *key* is the ID of the chunk it came from.
   - **value** lists the matching chunks, best first. Each one is a chunk of a PDF: its *chunk* field holds the chunk's text, and *title* and *blob_path* identify the PDF it came from. *@search.rerankerScore* shows how relevant the semantic ranker judged the chunk, from 0 to 4, and *@search.captions* highlights the most relevant sentences.

   Scroll down to **value**. The top chunk is from the label and marketing claims policy.
5. Select the **Fields** tab to see how the index is structured. Notice the *chunk* text field and the **text_vector** field that holds its embedding.

## Run the Python notebook

1. In Visual Studio Code, open **src/notebooks/01-knowledge-base-and-mr1.ipynb**.
2. Run each cell in order. When prompted to select a kernel, select **Python Environments** and then **.venv**.
3. Follow the instructions in the notebook.

## See your knowledge base in the Azure portal

1. Return to your Foundry IQ service in the Azure portal.
2. From the left pane, select **Agentic retrieval** > **Knowledge sources**. Find the three document knowledge sources that the notebook created, such as **cocoarynth-production-knowledge-source**. Each one targets the matching index, such as **cocoarynth-production**. The two graph-enabled sources were created during setup.
3. Select **Agentic retrieval** > **Knowledge bases**. Open **cocoarynth-standard-knowledge-base**.
4. Look at which knowledge sources it uses, which chat completion model it uses for query planning and answer synthesis, and its retrieval reasoning effort.
5. Open **cocoarynth-mr1-knowledge-base** too. Notice that it uses the same three sources, but no chat completion model.

## 🍫 Food for thought

If you built a knowledge base over your own documents, how would you split them into knowledge sources? By team, by document type, or by who's allowed to see them?

Select **Next** to continue to entities and graphs.

===

# Part 2: Entities and graphs

A Pantry Lane customer has a chocolate wrapper with batch code **EC26-0811** and wants to know which farms grew its cacao. A single chunk can mention a batch or a farm, but a graph makes the connection explicit: **Batch → BeanLot ← Farm**.

The lab includes an ontology and entity graph prepared from the source PDFs. The ontology defines entity types and relationships, and each graph assertion links back to a source chunk.

The Azure portal doesn't show graphs yet, so this lab includes a small web app, the **Cocoarynth graph explorer**, for looking at the graph visually.

## Start the graph explorer

1. In Visual Studio Code, select **Terminal** > **New Terminal**.
2. Wait a few seconds for the Python virtual environment to be activated in the terminal.
3. Run this command to start the app:

    +++python src\explorer\app.py+++

4. The app opens in your browser at +++http://localhost:8765+++. If it doesn't, open that address yourself. Keep the terminal running for the rest of the lab.

## Explore the ontology

The **Graph ontology** tab shows the graph's schema. Each circle is an entity type, and each arrow is a relationship from its domain (subject type) to its range (object type).

1. Select the **BeanLot** circle. The panel lists the relationships to and from a bean lot.
2. In the panel, select **Batch → madeFrom** and then **Farm → contributedTo**. These two relationships connect a batch to the farms that grew its beans.

## Explore the graph

1. Select the **Graph entities** tab. It opens with batch **EC26-0811** and the entities directly connected to it.
2. In the panel, look at the **batchCode** property and the **madeFrom** relationship. **madeFrom** shows that batch EC26-0811 was made from bean lot **EC26-L07**. That's the first step from the batch to its farms.
3. Select the **EC26-L07** bean lot circle to add its neighbors to the diagram. Find the two farms that contributed to it.
4. Select a **contributedTo** arrow, or select it in the panel's list of relationships. The panel shows the assertion, exact evidence excerpts, and the original PDF chunk it came from. Select the PDF name to open the original document.

## Read the ontology file

The ontology is saved in an OWL file, written as XML. The **Graph ontology** tab draws its diagram from the same file.

1. In Visual Studio Code, open **data/graph-data/cocoarynth.owl**.
2. Look through its elements:
   - Each **owl:Class** element is an entity type, with an **rdfs:label** and an **rdfs:comment** that describes it. You'll see entity types like *Batch*, *BeanLot*, and *Farm*.
   - Each **owl:ObjectProperty** element is a relationship. Its **rdfs:domain** is the subject type and its **rdfs:range** is the object type. You'll see relationships like *madeFrom*, from *Batch* to *BeanLot*, and *contributedTo*, from *Farm* to *BeanLot*.
   - Each **owl:DatatypeProperty** element is a property with a plain value, like the *batchCode* of a *Batch*.
   - Each **rdfs:seeAlso** links to the PDF chunk that the declaration is based on.

## Run the notebook

In the notebook, you'll query the graph directly with GQL, then see how a knowledge base uses the graph to answer a question.

1. In Visual Studio Code, open **src/notebooks/02-entities-and-graphs.ipynb**.
2. Run each cell in order, using the same **.venv** kernel.
3. Follow the instructions in the notebook.

## 🍫 Food for thought

- What would the ontology for your organization's documents look like? Think of two entity types and a relationship between them, like *Batch → madeFrom → BeanLot*.
- Which questions do your users ask that need two or more records connected, like the batch-to-farm question in this part?

Select **Next** to continue to **Topics**.

===

# Part 3: Topics

An entity graph shows how specific things are connected. Topics group related chunks so you can explore a broader area of the documents.

The topics form a two-level hierarchy. Each has a title and description to help you choose an area to explore, and a centroid vector for finding similar chunks.

## Explore topics in the graph explorer

1. In the graph explorer, select the **Topics** tab. If you closed the app, start it again as described in Part 2.
2. In the **Topics** panel on the right, compare **Assigned during the build** with **Not assigned during the build**. The topic groups cover 97 of the 106 chunks.
3. Broad topics are on the left at level 0, and narrower child topics are on the right at level 1. Select a box to read its description. There are four roots and four children; two of the roots have no children.
4. Below the description, the panel lists the topic's nearest chunks, grouped by document. To find them, the explorer searches the full source index with the topic's centroid. Expand a chunk to read it, or select a document name to open the original PDF. Do the chunks have something in common?

## Read the sitemap ontology file

The sitemap connects broad topics to their children in the **cocoarynth-topics** index. Open its OWL schema to see the types and relationships you'll query.

1. In Visual Studio Code, open **data/graph-data/cocoarynth-sitemap.owl**. Like **cocoarynth.owl**, it's an OWL file written as XML, so it uses the same kinds of elements.
2. Look through its elements:
   - The **owl:Class** elements are its three entity types: *TopicGraph*, the whole sitemap; *Topic*, a topic; and *Vector*, a terminal topic's centroid.
   - The **owl:ObjectProperty** elements are its three relationships: *HasRootTopic*, from the graph to a broad topic; *HasSubTopic*, from a parent topic to a child; and *HasCentroidVector*, from a terminal topic to its vector.
   - The **owl:DatatypeProperty** elements are plain-value properties, like a topic's *title*, *description*, *level*, and *proportion*.
3. In the notebook, you'll follow these links with GQL, then use topic vectors to find related chunks in **cocoarynth-chunks**.

## Run the notebook

In the notebook, you'll look inside the topic graph to understand how the chunks were grouped, then compare what a topic knowledge base and the standard knowledge base retrieve for a customer complaint.

1. In Visual Studio Code, open **src/notebooks/03-topics.ipynb**.
2. Run each cell in order, using the same **.venv** kernel.
3. In the complaint investigation, compare the topic suggestions with the cited PDF evidence. Which records help distinguish a batch issue from a delivery issue?

## 🍫 Food for thought

Think about the three questions from this lab: the organic seal, the farms behind batch EC26-0811, and Larkspur's complaint. Which retrieval approach would you start with for each one, and why?

Select **Next** to review key takeaways and next steps.

===

# Summary

You've completed the lab on exploring Foundry IQ knowledge bases. You:

- Built a knowledge base over three document indexes, followed its citations back to the original documents, and compared it with the faster Microsoft Retriever 1.
- Followed a chocolate batch to its farms with an ontology, GQL queries, and graph provenance, and compared a graph-backed knowledge base with standard retrieval.
- Explored labeled topic groups, looked inside the topic graph with code and GQL to see how the chunks were grouped, and investigated a customer complaint with topics and PDF evidence.

| Need | Good starting point |
| --- | --- |
| Ground a direct question in original documents | Standard knowledge base |
| Respond quickly when the app already knows which source to use | Microsoft Retriever 1 (MR1) |
| Follow explicit relationships across records | Entity graph and GQL |
| Explore groups of related chunks and navigate their sitemap | Topics and sitemap GQL |

## Continue learning

- [What is Foundry IQ?](https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-foundry-iq) - Explore the full capabilities of Foundry IQ and how it integrates with other Microsoft Foundry and Azure services.
- [Design an index for agentic retrieval in Foundry IQ](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-index) - Best practices for structuring your data for agentic retrieval.
- [Create a knowledge base in Foundry IQ](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-knowledge-base) - Step-by-step guide to creating and configuring knowledge bases.
- [Create a knowledge source](https://learn.microsoft.com/azure/search/agentic-knowledge-source-overview) - Understand how to create and configure different data sources.
- [Use Microsoft Retriever 1](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-use-microsoft-retriever) - Get fast agentic retrieval from a Microsoft-hosted retriever without supplying your own model capacity.
- [Create and query an entity graph](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-entity-graph) - Turn documents into entities and relationships that a knowledge base can follow.
- [Configure topic graph retrieval](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-topic-graph) - Group related chunks into topics and route queries through them.

## Next steps

Here are some ways to apply what you've learned:

**Customize retrieval behavior** - Adjust reasoning effort levels, and configure custom retrieval and answer instructions for specific sources.

**Integrate with your data** - Replace the sample Cocoarynth indexes with your own enterprise content.

**Build a conversational interface** - Connect the knowledge base to an agent with additional tools and a chat UI for end users.
