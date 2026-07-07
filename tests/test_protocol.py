import unittest

from app.models import Opcode, TransactionRequestModel
from app.protocol import Simulator


class SimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.simulator = Simulator()

    def test_read_shared_from_dirty_owner_downgrades_owner(self) -> None:
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.READ_SHARED,
                src_id="RN0",
                address="0x2000",
            )
        )

        entry = next(item for item in result.snapshot.snoop_filter if item.address == "0x2000")
        self.assertIsNone(entry.owner)
        self.assertEqual(entry.state_hint, "SharedClean")
        self.assertEqual(entry.sharers, ["RN0", "RN1"])

    def test_write_unique_invalidates_other_sharer(self) -> None:
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.WRITE_UNIQUE,
                src_id="RN0",
                address="0x1000",
                data="0xFACECAFE",
            )
        )

        entry = next(item for item in result.snapshot.snoop_filter if item.address == "0x1000")
        self.assertEqual(entry.owner, "RN0")
        self.assertEqual(entry.sharers, [])
        rn1_lines = result.snapshot.caches.get("RN1", [])
        self.assertFalse(any(line.address == "0x1000" for line in rn1_lines))

    def test_clean_shared_snoops_dirty_owner(self) -> None:
        """RN0 CleanShared on 0x2000 should snoop RN1 (UD owner) and downgrade it to SC."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.CLEAN_SHARED,
                src_id="RN0",
                address="0x2000",
            )
        )

        entry = next(item for item in result.snapshot.snoop_filter if item.address == "0x2000")
        # Dirty owner must be cleared
        self.assertIsNone(entry.owner)
        self.assertEqual(entry.state_hint, "SharedClean")
        # Both RN0 and RN1 should now be sharers
        self.assertIn("RN0", entry.sharers)
        self.assertIn("RN1", entry.sharers)
        # RN1's cache should be downgraded from UD to SC
        rn1_lines = result.snapshot.caches.get("RN1", [])
        rn1_line = next(l for l in rn1_lines if l.address == "0x2000")
        self.assertEqual(rn1_line.state, "SC")
        # Verify a SnpCleanShared event was generated toward RN1
        snoop_events = [e for e in result.events if "Snoop" in e.title and e.dst == "RN1"]
        self.assertTrue(len(snoop_events) > 0)


if __name__ == "__main__":
    unittest.main()
