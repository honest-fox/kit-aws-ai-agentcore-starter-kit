# Extension guide: your own knowledge base

Kit's knowledge base is a standard Bedrock Knowledge Base backed by S3
Vectors. The sample corpus is just files in a folder — swapping in your
own data is a replace-and-redeploy.

## The five-minute version

1. Delete the sample files in `sample-data/` (keep the folder).
2. Drop in your own documents — Markdown, plain text, HTML, PDF, and DOCX
   all work. Start small: a product FAQ, your policies, a runbook.
3. Update the knowledge-base hint in `app/kit/main.py` (the
   `DEFAULT_SYSTEM_PROMPT` addition that mentions Kookaburra Coffee) to
   describe *your* corpus so the agent knows when to retrieve.
4. Redeploy:

```bash
agentcore deploy
```

The deploy re-uploads the corpus and re-runs ingestion automatically.
Give it a few minutes, then ask the agent something only your documents
answer.

## How it works

- **Embedding:** Amazon Titan Text Embeddings v2 (1024 dimensions)
- **Storage:** S3 Vectors — no OpenSearch cluster, no idle cost
- **Chunking:** Bedrock's default (roughly 300-token chunks). For very
  long or highly structured documents, configure a chunking strategy on
  the `CfnDataSource` in `agentcore/cdk/lib/kit-knowledge-base.ts`.
- **Retrieval:** the agent's `retrieve` tool queries the KB and cites
  scored passages; the relevance threshold lives in the tool's
  `MIN_SCORE` environment variable if you need to tune it.

## Scaling up

The sample setup comfortably handles thousands of documents. Beyond that,
or for sources like Confluence, SharePoint, or a website crawl, Bedrock
data-source connectors plug into the same knowledge base — or talk to
[Honest Fox](https://honestfox.com.au) about doing it properly.
