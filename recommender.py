import numpy as np
from sentence_transformers import SentenceTransformer
from paper import ArxivPaper
from datetime import datetime

def rerank_paper(candidate:list[ArxivPaper],corpus:list[dict],model:str='avsolatorio/GIST-small-Embedding-v0') -> list[ArxivPaper]:
    for attempt in range(3):
        try:
            encoder = SentenceTransformer(model)
            break
        except Exception as e:
            if attempt < 2:
                wait = 30 * (attempt + 1)  # 30s, 60s
                logger.warning(f"Failed to load model (attempt {attempt+1}/3), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Failed to load model after 3 attempts: {e}") from e

    # encoder = SentenceTransformer(model)
    #sort corpus by date, from newest to oldest
    corpus = sorted(corpus,key=lambda x: datetime.strptime(x['data']['dateAdded'], '%Y-%m-%dT%H:%M:%SZ'),reverse=True)
    time_decay_weight = 1 / (1 + np.log10(np.arange(len(corpus)) + 1))
    time_decay_weight = time_decay_weight / time_decay_weight.sum()
    corpus_feature = encoder.encode([paper['data']['abstractNote'] for paper in corpus])
    candidate_feature = encoder.encode([paper.summary for paper in candidate])
    sim = encoder.similarity(candidate_feature,corpus_feature) # [n_candidate, n_corpus]
    scores = (sim * time_decay_weight).sum(axis=1) * 10 # [n_candidate]
    for s,c in zip(scores,candidate):
        c.score = s.item()
    candidate = sorted(candidate,key=lambda x: x.score,reverse=True)
    return candidate
