import unittest

from app.models import Opcode, TransactionRequestModel
from app.protocol import Simulator


class SimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.simulator = Simulator()

    # ------------------------------------------------------------------
    # Existing tests
    # ------------------------------------------------------------------
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
        self.assertIsNone(entry.owner)
        self.assertEqual(entry.state_hint, "SharedClean")
        self.assertIn("RN0", entry.sharers)
        self.assertIn("RN1", entry.sharers)
        rn1_lines = result.snapshot.caches.get("RN1", [])
        rn1_line = next(l for l in rn1_lines if l.address == "0x2000")
        self.assertEqual(rn1_line.state, "SC")
        snoop_events = [e for e in result.events if "Snoop" in e.title and e.dst == "RN1"]
        self.assertTrue(len(snoop_events) > 0)

    # ------------------------------------------------------------------
    # ReadNoSnp
    # ------------------------------------------------------------------
    def test_read_no_snp_fetches_from_home_without_snoop(self) -> None:
        """ReadNoSnp should read from home without issuing any snoops."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.READ_NO_SNP,
                src_id="RN0",
                address="0x1800",
            )
        )
        # No snoop events should be generated
        snoop_events = [e for e in result.events if e.channel == "SNP"]
        self.assertEqual(len(snoop_events), 0)
        # Data should come from home (SN0 has 0x1800 = 0xBBBB2222)
        comp_data = [e for e in result.events if e.packet and e.packet.opcode == "CompData"]
        self.assertTrue(len(comp_data) > 0)
        self.assertEqual(comp_data[0].packet.payload, "0xBBBB2222")

    # ------------------------------------------------------------------
    # ReadOnce
    # ------------------------------------------------------------------
    def test_read_once_from_dirty_owner(self) -> None:
        """ReadOnce on 0x2000 should snoop RN1 (UD) and deliver data to RN0."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.READ_ONCE,
                src_id="RN0",
                address="0x2000",
            )
        )
        # RN1 should be snooped
        snoop_events = [e for e in result.events if e.channel == "SNP" and e.dst == "RN1"]
        self.assertTrue(len(snoop_events) > 0)
        # RN0 should have received data
        rn0_lines = result.snapshot.caches.get("RN0", [])
        rn0_line = next((l for l in rn0_lines if l.address == "0x2000"), None)
        self.assertIsNotNone(rn0_line)
        self.assertEqual(rn0_line.data, "0xBEEF0001")

    # ------------------------------------------------------------------
    # ReadClean
    # ------------------------------------------------------------------
    def test_read_clean_allocates_shared_clean(self) -> None:
        """ReadClean on 0x2000 should snoop dirty owner and allocate SC in RN0."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.READ_CLEAN,
                src_id="RN0",
                address="0x2000",
            )
        )
        rn0_lines = result.snapshot.caches.get("RN0", [])
        rn0_line = next(l for l in rn0_lines if l.address == "0x2000")
        self.assertEqual(rn0_line.state, "SC")
        entry = next(item for item in result.snapshot.snoop_filter if item.address == "0x2000")
        self.assertIsNone(entry.owner)
        self.assertIn("RN0", entry.sharers)

    # ------------------------------------------------------------------
    # ReadUnique
    # ------------------------------------------------------------------
    def test_read_unique_invalidates_all_sharers(self) -> None:
        """ReadUnique on 0x1000 should invalidate both RN0 and RN1, then grant unique to RN1."""
        sim = Simulator()
        # RN1 requests unique on 0x1000 (shared by RN0 and RN1)
        result = sim.simulate(
            TransactionRequestModel(
                opcode=Opcode.READ_UNIQUE,
                src_id="RN1",
                address="0x1000",
            )
        )
        entry = next(item for item in result.snapshot.snoop_filter if item.address == "0x1000")
        self.assertEqual(entry.owner, "RN1")
        self.assertEqual(entry.sharers, [])
        # RN0 should no longer have the line
        rn0_lines = result.snapshot.caches.get("RN0", [])
        self.assertFalse(any(l.address == "0x1000" for l in rn0_lines))

    # ------------------------------------------------------------------
    # ReadPreferUnique
    # ------------------------------------------------------------------
    def test_read_prefer_unique_no_sharers_returns_unique(self) -> None:
        """ReadPreferUnique on 0x1800 (no sharers) should return unique without snoops."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.READ_PREFER_UNIQUE,
                src_id="RN0",
                address="0x1800",
            )
        )
        snoop_events = [e for e in result.events if e.channel == "SNP"]
        self.assertEqual(len(snoop_events), 0)
        rn0_lines = result.snapshot.caches.get("RN0", [])
        rn0_line = next(l for l in rn0_lines if l.address == "0x1800")
        self.assertEqual(rn0_line.state, "UC")

    def test_read_prefer_unique_with_sharers_falls_back_to_shared(self) -> None:
        """ReadPreferUnique on 0x1000 (has sharers) should fall back to shared."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.READ_PREFER_UNIQUE,
                src_id="RN0",
                address="0x1000",
            )
        )
        # RN0 already has the line as SC, so it should be a hit
        # The line should remain shared
        entry = next(item for item in result.snapshot.snoop_filter if item.address == "0x1000")
        self.assertIn("RN0", entry.sharers)

    # ------------------------------------------------------------------
    # WriteNoSnpFull
    # ------------------------------------------------------------------
    def test_write_no_snp_full_writes_without_snoop(self) -> None:
        """WriteNoSnpFull should write data to home without issuing snoops."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.WRITE_NO_SNP_FULL,
                src_id="RN0",
                address="0x1800",
                data="0xDEADBEEF",
            )
        )
        snoop_events = [e for e in result.events if e.channel == "SNP"]
        self.assertEqual(len(snoop_events), 0)
        # DBIDResp should be present
        dbid_events = [e for e in result.events if e.packet and e.packet.opcode == "DBIDResp"]
        self.assertTrue(len(dbid_events) > 0)
        # Home memory should be updated
        sn0_lines = result.snapshot.caches.get("SN0", [])
        sn0_line = next(l for l in sn0_lines if l.address == "0x1800")
        self.assertEqual(sn0_line.data, "0xDEADBEEF")

    # ------------------------------------------------------------------
    # WriteBackFull
    # ------------------------------------------------------------------
    def test_write_back_full_evicts_dirty_line(self) -> None:
        """WriteBackFull from RN1 on 0x2000 should evict the dirty line."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.WRITE_BACK_FULL,
                src_id="RN1",
                address="0x2000",
            )
        )
        # RN1 should no longer have the line
        rn1_lines = result.snapshot.caches.get("RN1", [])
        self.assertFalse(any(l.address == "0x2000" for l in rn1_lines))
        # CompDBIDResp should be present
        comp_dbid = [e for e in result.events if e.packet and e.packet.opcode == "CompDBIDResp"]
        self.assertTrue(len(comp_dbid) > 0)

    # ------------------------------------------------------------------
    # WriteCleanFull
    # ------------------------------------------------------------------
    def test_write_clean_full_retains_as_clean(self) -> None:
        """WriteCleanFull from RN1 on 0x2000 should retain the line as SC."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.WRITE_CLEAN_FULL,
                src_id="RN1",
                address="0x2000",
                data="0xBEEF0099",
            )
        )
        rn1_lines = result.snapshot.caches.get("RN1", [])
        rn1_line = next(l for l in rn1_lines if l.address == "0x2000")
        self.assertEqual(rn1_line.state, "SC")
        self.assertEqual(rn1_line.data, "0xBEEF0099")

    # ------------------------------------------------------------------
    # WriteEvictFull
    # ------------------------------------------------------------------
    def test_write_evict_full_removes_clean_line(self) -> None:
        """WriteEvictFull from RN0 on 0x1000 should remove the line without data transfer."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.WRITE_EVICT_FULL,
                src_id="RN0",
                address="0x1000",
            )
        )
        rn0_lines = result.snapshot.caches.get("RN0", [])
        self.assertFalse(any(l.address == "0x1000" for l in rn0_lines))
        # No data channel events (clean eviction needs no data)
        dat_events = [e for e in result.events if e.channel == "DAT"]
        self.assertEqual(len(dat_events), 0)

    # ------------------------------------------------------------------
    # CleanUnique
    # ------------------------------------------------------------------
    def test_clean_unique_invalidates_peers_and_grants_unique(self) -> None:
        """CleanUnique from RN1 on 0x1000 should invalidate RN0 and grant unique to RN1."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.CLEAN_UNIQUE,
                src_id="RN1",
                address="0x1000",
            )
        )
        entry = next(item for item in result.snapshot.snoop_filter if item.address == "0x1000")
        self.assertEqual(entry.owner, "RN1")
        self.assertEqual(entry.sharers, [])
        self.assertEqual(entry.state_hint, "UniqueClean")
        rn0_lines = result.snapshot.caches.get("RN0", [])
        self.assertFalse(any(l.address == "0x1000" for l in rn0_lines))

    # ------------------------------------------------------------------
    # MakeUnique
    # ------------------------------------------------------------------
    def test_make_unique_invalidates_peers_no_data_fetch(self) -> None:
        """MakeUnique from RN1 on 0x1000 should invalidate RN0 without data transfer."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.MAKE_UNIQUE,
                src_id="RN1",
                address="0x1000",
            )
        )
        entry = next(item for item in result.snapshot.snoop_filter if item.address == "0x1000")
        self.assertEqual(entry.owner, "RN1")
        self.assertEqual(entry.state_hint, "UniqueClean")
        rn0_lines = result.snapshot.caches.get("RN0", [])
        self.assertFalse(any(l.address == "0x1000" for l in rn0_lines))

    # ------------------------------------------------------------------
    # CleanInvalid
    # ------------------------------------------------------------------
    def test_clean_invalid_cleans_and_invalidates_all(self) -> None:
        """CleanInvalid on 0x1000 should invalidate all copies (RN0, RN1)."""
        result = self.simulator.simulate(
            TransactionRequestModel(
                opcode=Opcode.CLEAN_INVALID,
                src_id="RN0",
                address="0x1000",
            )
        )
        entry = next(item for item in result.snapshot.snoop_filter if item.address == "0x1000")
        self.assertEqual(entry.state_hint, "Invalid")
        self.assertIsNone(entry.owner)
        self.assertEqual(entry.sharers, [])
        # Both RN0 and RN1 should no longer have the line
        rn0_lines = result.snapshot.caches.get("RN0", [])
        rn1_lines = result.snapshot.caches.get("RN1", [])
        self.assertFalse(any(l.address == "0x1000" for l in rn0_lines))
        self.assertFalse(any(l.address == "0x1000" for l in rn1_lines))


if __name__ == "__main__":
    unittest.main()
