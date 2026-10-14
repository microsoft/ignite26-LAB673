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

In this hands-on lab, you'll build Foundry IQ (Azure AI Search) knowledge bases using agentic retrieval for Cocoarynth Chocolate Works, a fictional bean-to-bar chocolate maker. Its records are scattered across farm logs, factory tests, shipping paperwork, retailer emails, and company policies. You'll connect a knowledge base to an uploaded policy file, then build a multi-source knowledge base over four search indexes to solve customer and retailer mysteries with grounded, citation-backed answers.

## Getting started

Follow the steps below to set up your environment and begin the lab.

### Sign into Windows

In the virtual machine, sign into Windows using the following credentials:

- **User name**: +++@lab.VirtualMachine(Win11-Pro-Base).Username+++  
- **Password**: +++@lab.VirtualMachine(Win11-Pro-Base).Password+++

### Access the lab repository

Once signed in to the Skillable environment, you'll find the lab repository already cloned on your desktop under the folder: **Desktop > ignite26-LAB673**.

> This folder contains all the code, notebooks, and resources you'll need for the lab.

### Open the project folder in Visual Studio Code

Open Visual Studio Code and select **File > Open Folder**. Then navigate to Desktop and select the **ignite26-LAB673** folder and then **Select Folder**.

> [!TIP]
>
> When prompted whether to trust the authors of the files, select **Yes, I trust the authors**.

### Verify the environment setup

All required Azure services including **Foundry IQ (Azure AI Search) with pre-indexed data** and **Azure OpenAI deployments** have already been provisioned for you.

<details>
<summary><strong>📋 What's pre-configured (click to expand for details)</strong></summary>

- **Foundry IQ (Azure AI Search)** - Serverless with four pre-created indexes
- **cocoarynth-origins:** Farm and supplier records, partly in Spanish
- **cocoarynth-quality:** Bean tests, holds, lab certificates, tasting panels, and batch records
- **cocoarynth-logistics-retail:** Bills of lading, carrier logs, retailer emails, agreements, and sales
- **cocoarynth-policies:** Company policies, guides, and reference documents
- **Azure OpenAI** - Deployed models **gpt-5.4** for chat completion and answer synthesis and **text-embedding-3-large** for vector embeddings
- **Pre-computed vectors** - All Cocoarynth document chunks are already vectorized and indexed

</details>

#### Verify environment variables

1. Open the **.env** file under the main project folder.  
2. Verify that it includes these environment variables:
   - *AZURE_SEARCH_SERVICE_ENDPOINT*
   - *AZURE_SEARCH_ADMIN_KEY*
   - *AZURE_OPENAI_ENDPOINT*
   - *AZURE_OPENAI_KEY*
   - *AZURE_OPENAI_CHATGPT_DEPLOYMENT*
   - *AZURE_OPENAI_CHATGPT_MODEL_NAME*
   - *AZURE_OPENAI_EMBEDDING_DEPLOYMENT*
   - *AZURE_TENANT_ID*

If these variables are present, proceed to verify the indexes in Azure Portal.

#### Verify indexes in Azure Portal

Confirm that the search indexes have been created successfully:

1. Open a web browser and navigate to the +++https://portal.azure.com+++.
2. Sign in using your lab credentials:
    - **Username**: +++@lab.CloudPortalCredential(User1).Username+++  
    - **Temporary Access Pass**: +++@lab.CloudPortalCredential(User1).AccessToken+++
3. In the Azure Portal search bar at the top, search for +++@lab.CloudResourceGroup(Lab673-ResourceGroup).Name+++ and open your lab resource group.
4. Select your AI Search service (it will look like *lab673-search-.....*).
5. In the left navigation menu, select **Search management** > **Indexes**.
6. You should see four indexes, each with a nonzero document count:
   - **cocoarynth-origins**
   - **cocoarynth-quality**
   - **cocoarynth-logistics-retail**
   - **cocoarynth-policies**

If your indexes are present and populated, your environment is ready to use. You can now proceed to start with the Jupyter notebooks.

### Work through the Jupyter notebooks

This lab includes progressive notebooks covering different knowledge base and source type patterns:

1. **Multi-source search indexes** - Build a knowledge base over an uploaded label claims policy, then a knowledge base over all four search indexes that solves mysteries whose clues are spread across documents

Start with **part1-standard-foundry-iq-kb.ipynb** in the **src/notebooks/** folder and progress through each notebook sequentially.

Once you've completed all the notebooks, select **Next** to review key takeaways and next steps.
