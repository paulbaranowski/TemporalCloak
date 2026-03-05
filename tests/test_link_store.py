import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from temporal_cloak.link_store import LinkStore


class TestLinkStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.store = LinkStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.tmpdir)

    def _create_link(self, link_id="abc123", message="hello", burn=False):
        self.store.create(
            link_id=link_id,
            message=message,
            image_path="/img/test.jpg",
            image_filename="test.jpg",
            created_at=1000.0,
            burn_after_reading=burn,
        )

    def test_create_and_get(self):
        self._create_link()
        link = self.store.get("abc123")
        self.assertIsNotNone(link)
        self.assertEqual(link["message"], "hello")
        self.assertEqual(link["image_filename"], "test.jpg")
        self.assertEqual(link["burn_after_reading"], 0)
        self.assertEqual(link["delivered"], 0)

    def test_get_nonexistent(self):
        self.assertIsNone(self.store.get("nope"))

    def test_delete(self):
        self._create_link()
        self.store.delete("abc123")
        self.assertIsNone(self.store.get("abc123"))

    def test_mark_delivered_normal(self):
        self._create_link()
        self.store.mark_delivered("abc123")
        link = self.store.get("abc123")
        self.assertIsNotNone(link)
        self.assertEqual(link["delivered"], 1)

    def test_mark_delivered_idempotent(self):
        self._create_link()
        self.store.mark_delivered("abc123")
        self.store.mark_delivered("abc123")
        link = self.store.get("abc123")
        self.assertIsNotNone(link)
        self.assertEqual(link["delivered"], 1)

    def test_mark_delivered_nonexistent(self):
        # Should not raise
        self.store.mark_delivered("nope")

    def test_burn_after_reading(self):
        self._create_link(burn=True)
        link = self.store.get("abc123")
        self.assertIsNotNone(link)
        self.assertEqual(link["burn_after_reading"], 1)

        self.store.mark_delivered("abc123")
        self.assertIsNone(self.store.get("abc123"))

    def test_persistence_across_reopen(self):
        self._create_link()
        self.store.close()

        store2 = LinkStore(self.db_path)
        link = store2.get("abc123")
        self.assertIsNotNone(link)
        self.assertEqual(link["message"], "hello")
        store2.close()

    def test_thread_safety(self):
        errors = []

        def worker(i):
            try:
                lid = f"link_{i}"
                self.store.create(
                    link_id=lid,
                    message=f"msg {i}",
                    image_path="/img/test.jpg",
                    image_filename="test.jpg",
                    created_at=float(i),
                )
                link = self.store.get(lid)
                if link is None or link["message"] != f"msg {i}":
                    errors.append(f"Thread {i}: unexpected result {link}")
            except Exception as e:
                errors.append(f"Thread {i}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
