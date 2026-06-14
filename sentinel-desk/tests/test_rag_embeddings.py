from __future__ import annotations

import tempfile
import unittest

from sentineldesk import db
from sentineldesk.agent.embeddings import HashEmbedder, cosine
from sentineldesk.agent.rag_index import (
    hybrid_search,
    index_emails,
    search_index,
    semantic_search,
)
from sentineldesk.config import get_paths
from sentineldesk.email.models import EmailMessage


def _email(message_id: str, subject: str, body: str) -> EmailMessage:
    return EmailMessage(
        message_id=message_id, thread_id=f"t-{message_id}", sender="sender@example.com",
        subject=subject, received_at="2026-06-01T00:00:00Z", body_text=body,
    )


def _seed(paths) -> None:
    db.init_db(paths)
    rows = [
        ("m-opt", "OPT application", "You must file Form I-765 for OPT employment authorization before the filing window closes."),
        ("m-rent", "Rent reminder", "Your monthly rent payment of $1850 is due on the first of July."),
        ("m-promo", "Hotel rewards", "Earn bonus loyalty points on your next hotel stay this summer."),
    ]
    for message_id, subject, body in rows:
        db.upsert_email_message(
            paths, message=_email(message_id, subject, body), facts=[], ingested_at="2026-06-01T00:00:00Z"
        )


class EmbedderTests(unittest.TestCase):
    def test_cosine_ranks_related_text_closer(self) -> None:
        embedder = HashEmbedder()
        opt = embedder.embed("opt employment authorization application")
        opt_similar = embedder.embed("application for opt employment authorization")
        unrelated = embedder.embed("hotel loyalty points reward stay")
        self.assertGreater(cosine(opt, opt_similar), cosine(opt, unrelated))


class RagEmailEmbeddingTests(unittest.TestCase):
    def test_index_emails_stores_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            _seed(paths)
            count = index_emails(paths, embedder=HashEmbedder())
            self.assertEqual(count, 3)
            chunks = db.list_rag_chunks(paths)
            self.assertTrue(chunks)
            self.assertTrue(all(isinstance(c.get("embedding"), list) and c["embedding"] for c in chunks))

    def test_semantic_search_finds_the_relevant_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            _seed(paths)
            embedder = HashEmbedder()
            index_emails(paths, embedder=embedder)
            results = semantic_search(paths, "employment authorization for OPT", embedder, limit=3)
            self.assertTrue(results)
            top_doc, top_score = results[0]
            self.assertIn("m-opt", str(top_doc.metadata.get("document_source_id")))
            self.assertGreater(top_score, 0.0)

    def test_hybrid_search_returns_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            _seed(paths)
            embedder = HashEmbedder()
            index_emails(paths, embedder=embedder)
            fused = hybrid_search(paths, "rent payment due", embedder, limit=2)
            self.assertTrue(fused)
            self.assertIn("m-rent", str(fused[0].metadata.get("document_source_id")))

    def test_index_emails_incremental_skips_already_embedded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            _seed(paths)
            embedder = HashEmbedder()
            self.assertEqual(index_emails(paths, embedder=embedder), 3)
            # a second incremental pass embeds nothing — all three are present
            self.assertEqual(index_emails(paths, embedder=embedder, skip_indexed=True), 0)
            # a newly arrived email is the only one embedded next time
            db.upsert_email_message(
                paths, message=_email("m-new", "New notice", "Some brand new content to embed."),
                facts=[], ingested_at="2026-06-02T00:00:00Z",
            )
            self.assertEqual(index_emails(paths, embedder=embedder, skip_indexed=True), 1)

    def test_index_without_embedder_still_keyword_searchable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            _seed(paths)
            index_emails(paths)  # no embedder
            # keyword search still works; semantic returns nothing (no vectors)
            self.assertTrue(search_index(paths, "rent payment", limit=2))
            self.assertEqual(semantic_search(paths, "rent payment", HashEmbedder(), limit=2), [])


class RagGroundedChatTests(unittest.TestCase):
    def test_open_ended_question_answers_from_email_rag(self) -> None:
        from sentineldesk.agent.graph import answer_question
        from sentineldesk.agent.schemas import Intent
        from sentineldesk.agent.tools import default_tool_registry

        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            _seed(paths)
            index_emails(paths, embedder=HashEmbedder())  # local home -> hash embedder in the tool too
            registry = default_tool_registry(paths)
            answer = answer_question(
                "tell me about my OPT employment authorization filing",
                messages=[], registry=registry,
            )
            self.assertEqual(answer.intent, Intent.GENERAL)
            self.assertTrue(answer.metadata.get("rag"))
            self.assertTrue(answer.citations)
            self.assertIn("OPT", " ".join(c.evidence for c in answer.citations))
            # the sources are surfaced as email cards (one per source email)
            cards = answer.metadata.get("cards")
            self.assertTrue(cards)
            self.assertTrue(all(card["kind"] == "email" and card["source_id"] for card in cards))
            self.assertEqual(len(cards), len({card["source_id"] for card in cards}))  # deduped

    def test_greeting_still_gets_capability_reply_not_rag(self) -> None:
        from sentineldesk.agent.graph import answer_question
        from sentineldesk.agent.schemas import Intent
        from sentineldesk.agent.tools import default_tool_registry

        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            _seed(paths)
            index_emails(paths, embedder=HashEmbedder())
            registry = default_tool_registry(paths)
            answer = answer_question("你好", messages=[], registry=registry)
            self.assertEqual(answer.intent, Intent.GENERAL)
            self.assertFalse(answer.metadata.get("rag"))
            self.assertIn("LifeAgent", answer.answer)


if __name__ == "__main__":
    unittest.main()
