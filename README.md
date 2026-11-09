<a name="start-building"></a>

<p align="center">
<img src="img/banner-ignite-26.png" alt="Microsoft Ignite 2026" width="100%"/>
</p>

# [Microsoft Ignite 2026](https://ignite.microsoft.com)

## 🔥LAB673: Turning data into agent-ready knowledge with Foundry IQ

### Session description

Use Foundry IQ to build a knowledge base for agentic retrieval over enterprise content. Connect your documents and configure retrieval to surface relevant context for complex questions.

### 🚀 Getting started

#### In a guided session

If you're following along during a live session:

1. Sign in to the lab environment provided for the session
2. Follow the lab instructions in the Skillable sidebar

#### On your own

If you're learning at your own pace:

1. Clone this repository
2. Deploy the Azure resources to your own subscription by following
   [Deploy to your own Azure subscription](deploy_yourself.md)
3. Follow the [lab instructions](instructions/skillable.md) and run the
   notebooks in [`src/notebooks/`](src/notebooks/). See the
   [source guide](src/README.md) for setup details.

The lab uses three search indexes: `cocoarynth-topics` for named topic vectors
and sitemap GQL, `cocoarynth-chunks` for PDF chunks and embeddings, and
`cocoarynth-graph` for ontology-constrained business triples. The
[business ontology](data/graph-data/cocoarynth.owl) is a checked-in OWL file,
not an index. Both the business graph and the topic sitemap use the November
inline-ontology private preview; the target Search service must have access.

### 🎯 Learning outcomes

By the end of this session, you will be able to:

- Build a Foundry IQ knowledge base over multiple indexes, follow its citations back to source documents, and compare standard agentic retrieval with Microsoft Retriever 1 (MR1)
- Use an ontology, GQL queries, and graph provenance to answer questions that follow explicit relationships across records
- Explore labeled topic groups and compare topic-based routing with direct vector search

### 💻 Technologies used

- [Foundry IQ](https://learn.microsoft.com/azure/foundry/agents/concepts/what-is-foundry-iq)
- [Agentic retrieval in Azure AI Search](https://learn.microsoft.com/azure/search/agentic-retrieval-overview)
- [Microsoft Foundry Models](https://learn.microsoft.com/azure/foundry/concepts/foundry-models-overview)

### 📚 Continue your learning

Pick your next step based on your learning style:

| Resource | What you'll get |
|----------|-----------------|
| **[Ignite 2026 Next Steps](https://aka.ms/ignite26-next-steps)** | Additional session repos and materials from Microsoft Ignite 2026 |
| **[Microsoft AI Skills Navigator](https://aka.ms/ignite26-asn)** | Discover AI skills, learning paths, and resources for your next step |
| **[Microsoft Learn](https://aka.ms/ignite26-learn)** | Official documentation and guided learning paths on these topics |
| **[Microsoft Foundry Community](https://aka.ms/MicrosoftFoundryDiscord-Ignite26)** | Connect with other learners and experts in our Discord community |

### 🌟 Microsoft Learn MCP Server

The Microsoft Learn MCP Server gives your AI agent direct access to Microsoft's official documentation — grounded, up-to-date answers about the topics in this session.

**GitHub Copilot CLI** — Install with:

```shell
copilot plugin install microsoftdocs/mcp
```

**VS Code** — One-click install:  
[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_Microsoft_Learn_MCP-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=microsoft-learn&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Flearn.microsoft.com%2Fapi%2Fmcp%22%7D)

For more information, visit the [Learn MCP Server repo](https://aka.ms/learnmcp).

### 👥 Content owners

<table>
<tr>
    <td align="center"><a href="https://github.com/pamelafox">
        <img src="https://github.com/pamelafox.png" width="100px;" alt="Pamela Fox"/><br />
        <sub><b>Pamela Fox</b></sub></a><br />
            <a href="https://github.com/pamelafox" title="talk">📢</a>
    </td>
    <td align="center"><a href="https://github.com/mattgotteiner">
        <img src="https://github.com/mattgotteiner.png" width="100px;" alt="Matt Gotteiner"/><br />
        <sub><b>Matt Gotteiner</b></sub></a><br />
            <a href="https://github.com/mattgotteiner" title="talk">📢</a>
    </td>
    <td align="center"><a href="https://github.com/aycabas">
        <img src="https://github.com/aycabas.png" width="100px;" alt="Ayca Bas"/><br />
        <sub><b>Ayca Bas</b></sub></a><br />
            <a href="https://github.com/aycabas" title="talk">📢</a>
    </td>
</tr></table>

### ⚖️ Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.

Any use of third-party trademarks or logos are subject to those third-party's policies.
