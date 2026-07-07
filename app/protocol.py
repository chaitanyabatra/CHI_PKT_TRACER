from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from fastapi import HTTPException

from .models import (
    AddressMapUpdateModel,
    AddressRegionModel,
    CacheLineModel,
    Channel,
    ClientStateModel,
    EventModel,
    HistoryEntryModel,
    LayoutUpdateModel,
    LinkModel,
    NodeKind,
    NodeModel,
    Opcode,
    PacketModel,
    SimulationResultModel,
    SimulationSnapshotModel,
    SnoopFilterEntryModel,
    TransactionRequestModel,
)


DEFAULT_CREDITS = {
    Channel.REQ.value: 8,
    Channel.SNP.value: 8,
    Channel.RSP.value: 8,
    Channel.DAT.value: 8,
    Channel.CRD.value: 8,
}


class Simulator:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.nodes: Dict[str, NodeModel] = {
            "RN0": NodeModel(
                node_id="RN0",
                label="RN-Fetch",
                kind=NodeKind.RN,
                color="#FF8A3D",
                x=180,
                y=160,
                description="Read-mostly requester driving instruction-side traffic.",
            ),
            "RN1": NodeModel(
                node_id="RN1",
                label="RN-Exec",
                kind=NodeKind.RN,
                color="#36D1C4",
                x=180,
                y=410,
                description="Write-capable requester with a dirty private line.",
            ),
            "ICN0": NodeModel(
                node_id="ICN0",
                label="ICN-Fabric",
                kind=NodeKind.ICN,
                color="#B48EFA",
                x=540,
                y=280,
                description="Coherent interconnect with a visible snoop filter.",
            ),
            "SN0": NodeModel(
                node_id="SN0",
                label="SN-DRAM-A",
                kind=NodeKind.SN,
                color="#5DA9FF",
                x=900,
                y=150,
                description="Home node for low memory window 0x0000-0x1FFF.",
            ),
            "SN1": NodeModel(
                node_id="SN1",
                label="SN-DRAM-B",
                kind=NodeKind.SN,
                color="#F95D8E",
                x=900,
                y=410,
                description="Home node for upper memory window 0x2000-0x3FFF.",
            ),
        }

        self.links: List[LinkModel] = [
            LinkModel(src="RN0", dst="ICN0", label="CHI link A"),
            LinkModel(src="RN1", dst="ICN0", label="CHI link B"),
            LinkModel(src="ICN0", dst="SN0", label="Home path 0"),
            LinkModel(src="ICN0", dst="SN1", label="Home path 1"),
        ]

        self.address_map: List[AddressRegionModel] = [
            AddressRegionModel(
                region_id="sn0-low",
                node_id="SN0",
                label="DDR Window A",
                base="0x0000",
                limit="0x1FFF",
                color="#5DA9FF",
            ),
            AddressRegionModel(
                region_id="sn1-high",
                node_id="SN1",
                label="DDR Window B",
                base="0x2000",
                limit="0x3FFF",
                color="#F95D8E",
            ),
        ]

        self.caches: Dict[str, Dict[int, Dict[str, str]]] = {
            "RN0": {
                0x1000: {
                    "state": "SC",
                    "data": "0xAAAA1111",
                    "note": "Shared clean line mirrored in RN1.",
                }
            },
            "RN1": {
                0x1000: {
                    "state": "SC",
                    "data": "0xAAAA1111",
                    "note": "Sharer that will be invalidated on WriteUnique.",
                },
                0x2000: {
                    "state": "UD",
                    "data": "0xBEEF0001",
                    "note": "Dirty owner used to demonstrate snooped reads.",
                },
            },
            "SN0": {
                0x1000: {
                    "state": "UC",
                    "data": "0xAAAA1111",
                    "note": "Home memory view for shared line.",
                },
                0x1800: {
                    "state": "UC",
                    "data": "0xBBBB2222",
                    "note": "Spare home line with no sharers.",
                },
            },
            "SN1": {
                0x2000: {
                    "state": "UC",
                    "data": "0xBEEF0000",
                    "note": "Home copy behind a dirty RN owner.",
                },
                0x2800: {
                    "state": "UC",
                    "data": "0xCCCC3333",
                    "note": "Clean line for CMO experiments.",
                },
            },
        }

        self.snoop_filter: Dict[int, Dict[str, object]] = {
            0x1000: {
                "home": "SN0",
                "owner": None,
                "sharers": {"RN0", "RN1"},
                "state_hint": "SharedClean",
                "last_opcode": "Seed",
                "last_txn_id": 0,
            },
            0x2000: {
                "home": "SN1",
                "owner": "RN1",
                "sharers": set(),
                "state_hint": "UniqueDirty",
                "last_opcode": "Seed",
                "last_txn_id": 0,
            },
            0x2800: {
                "home": "SN1",
                "owner": None,
                "sharers": {"RN1"},
                "state_hint": "SharedClean",
                "last_opcode": "Seed",
                "last_txn_id": 0,
            },
        }

        self.credits: Dict[str, Dict[str, int]] = {
            node_id: deepcopy(DEFAULT_CREDITS) for node_id in self.nodes
        }
        self.history: List[HistoryEntryModel] = []
        self._next_txn_id = 17

    def load_state(self, state: ClientStateModel) -> None:
        """Restore mutable simulator state from client-provided snapshot."""
        # Rebuild caches: Dict[str, Dict[int, Dict[str, str]]]
        self.caches = {}
        for node_id, lines in state.caches.items():
            self.caches[node_id] = {}
            for line in lines:
                addr = self._parse_hex(line.address)
                self.caches[node_id][addr] = {
                    "state": line.state,
                    "data": line.data,
                    "note": line.note,
                }
        # Rebuild snoop filter: Dict[int, Dict[str, object]]
        self.snoop_filter = {}
        for entry in state.snoop_filter:
            addr = self._parse_hex(entry.address)
            self.snoop_filter[addr] = {
                "home": entry.home,
                "owner": entry.owner,
                "sharers": set(entry.sharers),
                "state_hint": entry.state_hint,
                "last_opcode": entry.last_opcode,
                "last_txn_id": entry.last_txn_id,
            }
        # Restore credits
        self.credits = deepcopy(state.credits)
        # Restore history
        self.history = list(state.history)
        # Restore txn counter
        self._next_txn_id = state.next_txn_id

    def snapshot(self) -> SimulationSnapshotModel:
        cache_snapshot: Dict[str, List[CacheLineModel]] = {}
        for node_id, lines in self.caches.items():
            cache_snapshot[node_id] = [
                CacheLineModel(
                    address=self._fmt_addr(address),
                    state=line["state"],
                    data=line["data"],
                    note=line["note"],
                )
                for address, line in sorted(lines.items())
            ]

        sf_snapshot = [
            SnoopFilterEntryModel(
                address=self._fmt_addr(address),
                home=str(entry["home"]),
                owner=entry["owner"],
                sharers=sorted(entry["sharers"]),
                state_hint=str(entry["state_hint"]),
                last_opcode=str(entry["last_opcode"]),
                last_txn_id=int(entry["last_txn_id"]),
            )
            for address, entry in sorted(self.snoop_filter.items())
        ]

        return SimulationSnapshotModel(
            nodes=list(self.nodes.values()),
            links=self.links,
            address_map=self.address_map,
            caches=cache_snapshot,
            snoop_filter=sf_snapshot,
            credits=deepcopy(self.credits),
            history=self.history[:12],
            next_txn_id=self._next_txn_id,
        )

    def update_layout(self, update: LayoutUpdateModel) -> SimulationSnapshotModel:
        for position in update.positions:
            node = self.nodes.get(position.node_id)
            if not node:
                raise HTTPException(status_code=404, detail=f"Unknown node {position.node_id}")
            self.nodes[position.node_id] = node.model_copy(
                update={"x": position.x, "y": position.y}
            )
        return self.snapshot()

    def update_address_map(self, update: AddressMapUpdateModel) -> SimulationSnapshotModel:
        regions_by_id = {region.region_id: region for region in self.address_map}
        seen_ranges: List[tuple[int, int, str]] = []

        for edited in update.regions:
            region = regions_by_id.get(edited.region_id)
            if not region:
                raise HTTPException(status_code=404, detail=f"Unknown region {edited.region_id}")

            base_value = self._parse_hex(edited.base)
            limit_value = self._parse_hex(edited.limit)
            if base_value > limit_value:
                raise HTTPException(
                    status_code=400,
                    detail=f"Region {edited.region_id} has base above limit.",
                )

            seen_ranges.append((base_value, limit_value, edited.region_id))
            regions_by_id[edited.region_id] = region.model_copy(
                update={
                    "base": self._fmt_addr(base_value),
                    "limit": self._fmt_addr(limit_value),
                }
            )

        seen_ranges.sort(key=lambda item: item[0])
        for index in range(1, len(seen_ranges)):
            previous = seen_ranges[index - 1]
            current = seen_ranges[index]
            if current[0] <= previous[1]:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Address map overlap between {previous[2]} and {current[2]}."
                    ),
                )

        self.address_map = [regions_by_id[region.region_id] for region in self.address_map]
        return self.snapshot()

    def simulate(self, request: TransactionRequestModel) -> SimulationResultModel:
        # If client sends state, restore it before simulating
        if request.client_state is not None:
            self.load_state(request.client_state)

        address = self._parse_hex(request.address)
        src_id = request.src_id
        if src_id not in self.nodes:
            raise HTTPException(status_code=404, detail=f"Unknown src_id {src_id}")

        if self.nodes[src_id].kind != NodeKind.RN:
            raise HTTPException(status_code=400, detail="Transactions must originate from an RN.")

        home_id = request.tgt_id or self._home_for_address(address)
        if home_id not in self.nodes:
            raise HTTPException(status_code=404, detail=f"Unknown tgt_id {home_id}")

        txn_id = request.txn_id or self._claim_txn_id()
        packet = PacketModel(
            opcode=request.opcode.value,
            srcid=src_id,
            tgtid=home_id,
            txnid=txn_id,
            addr=self._fmt_addr(address),
            size=request.size,
            qos=request.qos,
            ns=request.ns,
            attributes={
                "snpattr": "InnerShareable",
                "memattr": "Cacheable",
                "order": "RequestOrder",
            },
            payload=request.data,
        )

        entry = self._ensure_entry(address, home_id)
        events: List[EventModel] = []

        self._send(
            events,
            channel=Channel.REQ.value,
            src=src_id,
            dst="ICN0",
            title=f"{packet.opcode} issued",
            detail=(
                f"{src_id} launches {packet.opcode} for {packet.addr} toward home node {home_id}."
            ),
            packet=packet,
        )
        self._credit(events, src="ICN0", dst=src_id, channel=Channel.REQ.value)
        self._state(
            events,
            src="ICN0",
            dst="ICN0",
            title="Snoop filter lookup",
            detail=(
                f"Entry for {packet.addr}: owner={entry['owner'] or 'none'}, sharers={self._format_sharers(entry['sharers'])}."
            ),
        )

        if request.opcode == Opcode.READ_SHARED:
            summary = self._simulate_read_shared(events, packet, address, src_id, home_id, entry)
        elif request.opcode == Opcode.WRITE_UNIQUE:
            summary = self._simulate_write_unique(
                events, packet, address, src_id, home_id, entry, request.data
            )
        elif request.opcode == Opcode.CLEAN_SHARED:
            summary = self._simulate_clean_shared(events, packet, address, src_id, home_id, entry)
        elif request.opcode == Opcode.MAKE_INVALID:
            summary = self._simulate_make_invalid(events, packet, address, src_id, home_id, entry)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported opcode {request.opcode.value}")

        entry["last_opcode"] = packet.opcode
        entry["last_txn_id"] = txn_id
        history_entry = HistoryEntryModel(
            txnid=txn_id,
            opcode=packet.opcode,
            srcid=src_id,
            tgtid=home_id,
            addr=packet.addr,
            summary=summary,
            issued_at=datetime.now(timezone.utc).strftime("%H:%M:%SZ"),
        )
        self.history.insert(0, history_entry)
        self.history = self.history[:12]

        return SimulationResultModel(
            transaction=packet,
            events=events,
            snapshot=self.snapshot(),
            summary=summary,
        )

    def _simulate_read_shared(
        self,
        events: List[EventModel],
        packet: PacketModel,
        address: int,
        src_id: str,
        home_id: str,
        entry: Dict[str, object],
    ) -> str:
        local_line = self.caches.get(src_id, {}).get(address)
        if local_line and local_line["state"] != "I":
            self._state(
                events,
                src=src_id,
                dst=src_id,
                title="Read hit",
                detail=f"{src_id} already holds {packet.addr} in state {local_line['state']}.",
            )
            self._send(
                events,
                channel=Channel.RSP.value,
                src="ICN0",
                dst=src_id,
                title="Read completed locally",
                detail=f"No snoop required. ICN closes txn {packet.txnid} as a local coherent hit.",
                packet=packet,
            )
            self._credit(events, src=src_id, dst="ICN0", channel=Channel.RSP.value)
            return f"{packet.opcode} hit in {src_id}; cache and snoop filter stay unchanged."

        owner = entry["owner"]
        if owner and owner != src_id:
            snoop_packet = packet.model_copy(update={"opcode": "SnpShared", "tgtid": owner})
            self._send(
                events,
                channel=Channel.SNP.value,
                src="ICN0",
                dst=owner,
                title="Dirty owner snooped",
                detail=f"ICN0 asks {owner} to downgrade and supply shared data for {packet.addr}.",
                packet=snoop_packet,
            )
            self._credit(events, src=owner, dst="ICN0", channel=Channel.SNP.value)

            owner_line = self.caches.get(owner, {}).get(address)
            data = owner_line["data"] if owner_line else self._home_line(home_id, address)["data"]
            self._send(
                events,
                channel=Channel.RSP.value,
                src=owner,
                dst="ICN0",
                title="Snoop response returned",
                detail=f"{owner} acknowledges the snoop and allows the line to become shared-clean.",
                packet=packet.model_copy(update={"opcode": "SnpRespData", "payload": data}),
            )
            self._credit(events, src="ICN0", dst=owner, channel=Channel.RSP.value)
            self._send(
                events,
                channel=Channel.DAT.value,
                src=owner,
                dst=src_id,
                title="Forwarded data",
                detail=f"{owner} forwards the freshest copy of {packet.addr} directly to {src_id}.",
                packet=packet.model_copy(update={"opcode": "CompData", "payload": data}),
            )
            self._credit(events, src=src_id, dst=owner, channel=Channel.DAT.value)
            self._send(
                events,
                channel=Channel.RSP.value,
                src="ICN0",
                dst=src_id,
                title="Read response",
                detail=f"ICN0 confirms txn {packet.txnid} completed after the snoop path.",
                packet=packet.model_copy(update={"opcode": "RespOk"}),
            )
            self._credit(events, src=src_id, dst="ICN0", channel=Channel.RSP.value)

            self.caches.setdefault(src_id, {})[address] = {
                "state": "SC",
                "data": data,
                "note": f"Filled by remote owner {owner} after snoop.",
            }
            if owner_line:
                owner_line["state"] = "SC"
                owner_line["note"] = f"Downgraded to shared after serving {src_id}."

            home_line = self._home_line(home_id, address)
            home_line["data"] = data
            home_line["note"] = f"Refreshed after dirty owner {owner} supplied data."

            entry["owner"] = None
            entry["sharers"] = {src_id, owner}
            entry["state_hint"] = "SharedClean"
            return f"{packet.opcode} snooped dirty owner {owner}; {src_id} and {owner} now share {packet.addr}."

        self._send(
            events,
            channel=Channel.REQ.value,
            src="ICN0",
            dst=home_id,
            title="Home lookup",
            detail=f"ICN0 forwards the read to {home_id} because no external dirty owner is tracked.",
            packet=packet,
        )
        self._credit(events, src=home_id, dst="ICN0", channel=Channel.REQ.value)
        home_line = self._home_line(home_id, address)
        data = home_line["data"]
        self._send(
            events,
            channel=Channel.DAT.value,
            src=home_id,
            dst=src_id,
            title="Home data return",
            detail=f"{home_id} returns clean data for {packet.addr} to requester {src_id}.",
            packet=packet.model_copy(update={"opcode": "CompData", "payload": data}),
        )
        self._credit(events, src=src_id, dst=home_id, channel=Channel.DAT.value)
        self._send(
            events,
            channel=Channel.RSP.value,
            src="ICN0",
            dst=src_id,
            title="Read response",
            detail=f"ICN0 finalizes the home-node read for txn {packet.txnid}.",
            packet=packet.model_copy(update={"opcode": "RespOk"}),
        )
        self._credit(events, src=src_id, dst="ICN0", channel=Channel.RSP.value)

        self.caches.setdefault(src_id, {})[address] = {
            "state": "SC",
            "data": data,
            "note": f"Allocated from home node {home_id}.",
        }
        entry["owner"] = None
        entry["sharers"] = set(entry["sharers"]) | {src_id}
        entry["state_hint"] = "SharedClean"
        return f"{packet.opcode} completed from {home_id}; {src_id} now has a shared-clean copy of {packet.addr}."

    def _simulate_write_unique(
        self,
        events: List[EventModel],
        packet: PacketModel,
        address: int,
        src_id: str,
        home_id: str,
        entry: Dict[str, object],
        data: Optional[str],
    ) -> str:
        payload = data or "0xDADA5501"
        snoop_targets = set(entry["sharers"])
        if entry["owner"]:
            snoop_targets.add(str(entry["owner"]))
        snoop_targets.discard(src_id)

        for target in sorted(snoop_targets):
            self._send(
                events,
                channel=Channel.SNP.value,
                src="ICN0",
                dst=target,
                title="Invalidate sharer",
                detail=f"ICN0 sends SnpMakeInvalid to {target} for upcoming WriteUnique on {packet.addr}.",
                packet=packet.model_copy(update={"opcode": "SnpMakeInvalid", "tgtid": target}),
            )
            self._credit(events, src=target, dst="ICN0", channel=Channel.SNP.value)
            self._send(
                events,
                channel=Channel.RSP.value,
                src=target,
                dst="ICN0",
                title="Invalidate ack",
                detail=f"{target} invalidates its local copy of {packet.addr} and returns an ack.",
                packet=packet.model_copy(update={"opcode": "SnpRespI", "tgtid": "ICN0"}),
            )
            self._credit(events, src="ICN0", dst=target, channel=Channel.RSP.value)
            self.caches.get(target, {}).pop(address, None)

        self._send(
            events,
            channel=Channel.DAT.value,
            src=src_id,
            dst=home_id,
            title="Write data",
            detail=f"{src_id} pushes new write data for {packet.addr} into home node {home_id}.",
            packet=packet.model_copy(update={"opcode": "WriteData", "payload": payload}),
        )
        self._credit(events, src=home_id, dst=src_id, channel=Channel.DAT.value)
        self._send(
            events,
            channel=Channel.RSP.value,
            src="ICN0",
            dst=src_id,
            title="Write response",
            detail=f"ICN0 grants unique ownership of {packet.addr} to {src_id}.",
            packet=packet.model_copy(update={"opcode": "Comp"}),
        )
        self._credit(events, src=src_id, dst="ICN0", channel=Channel.RSP.value)

        self.caches.setdefault(src_id, {})[address] = {
            "state": "UD",
            "data": payload,
            "note": "New unique dirty owner after WriteUnique.",
        }
        home_line = self._home_line(home_id, address)
        home_line["data"] = payload
        home_line["note"] = f"Home memory updated by {src_id} for txn {packet.txnid}."

        entry["owner"] = src_id
        entry["sharers"] = set()
        entry["state_hint"] = "UniqueDirty"
        return f"{packet.opcode} invalidated peer copies and moved unique ownership of {packet.addr} to {src_id}."

    def _simulate_clean_shared(
        self,
        events: List[EventModel],
        packet: PacketModel,
        address: int,
        src_id: str,
        home_id: str,
        entry: Dict[str, object],
    ) -> str:
        # Check snoop filter for a dirty owner that needs to be cleaned
        owner = entry["owner"]
        if owner:
            # Snoop the dirty owner so it writes back and downgrades to SC
            snoop_packet = packet.model_copy(update={"opcode": "SnpCleanShared", "tgtid": owner})
            self._send(
                events,
                channel=Channel.SNP.value,
                src="ICN0",
                dst=owner,
                title=f"Snoop dirty owner {owner}",
                detail=f"ICN0 sends SnpCleanShared to {owner} — it must write back {packet.addr} and downgrade.",
                packet=snoop_packet,
            )
            self._credit(events, src=owner, dst="ICN0", channel=Channel.SNP.value)

            # Owner writes back dirty data to home
            owner_line = self.caches.get(owner, {}).get(address)
            data = owner_line["data"] if owner_line else self._home_line(home_id, address)["data"]
            self._send(
                events,
                channel=Channel.DAT.value,
                src=owner,
                dst=home_id,
                title=f"{owner} writes back dirty data",
                detail=f"{owner} returns dirty copy of {packet.addr} to home {home_id} via CopyBackWrData.",
                packet=packet.model_copy(update={"opcode": "CopyBackWrData", "payload": data, "tgtid": home_id}),
            )
            self._credit(events, src=home_id, dst=owner, channel=Channel.DAT.value)

            # Owner sends snoop response confirming downgrade
            self._send(
                events,
                channel=Channel.RSP.value,
                src=owner,
                dst="ICN0",
                title=f"{owner} snoop ack",
                detail=f"{owner} confirms it has downgraded {packet.addr} from dirty to shared-clean.",
                packet=packet.model_copy(update={"opcode": "SnpResp_SC", "tgtid": "ICN0"}),
            )
            self._credit(events, src="ICN0", dst=owner, channel=Channel.RSP.value)

            # Update owner's cache to SC
            if owner_line:
                owner_line["state"] = "SC"
                owner_line["note"] = f"Downgraded from UD to SC by CleanShared snoop from {src_id}."

            # Update home memory with written-back data
            home_line = self._home_line(home_id, address)
            home_line["data"] = data
            home_line["note"] = f"Refreshed by writeback from {owner} due to CleanShared."

            # Clear dirty ownership in snoop filter, owner becomes a sharer
            entry["owner"] = None
            entry["sharers"] = set(entry["sharers"]) | {owner}

        # Forward CMO to home
        self._send(
            events,
            channel=Channel.REQ.value,
            src="ICN0",
            dst=home_id,
            title="CMO routed to home",
            detail=f"ICN0 forwards the dataless CleanShared request for {packet.addr} to {home_id}.",
            packet=packet,
        )
        self._credit(events, src=home_id, dst="ICN0", channel=Channel.REQ.value)

        self._state(
            events,
            src=src_id,
            dst=src_id,
            title="Requester cache cleaned",
            detail=f"{src_id} holds {packet.addr} as shared-clean after the CMO completes.",
        )

        self._send(
            events,
            channel=Channel.RSP.value,
            src="ICN0",
            dst=src_id,
            title="CMO complete",
            detail=f"CleanShared for {packet.addr} is done — all copies are now clean.",
            packet=packet.model_copy(update={"opcode": "Comp"}),
        )
        self._credit(events, src=src_id, dst="ICN0", channel=Channel.RSP.value)

        # Update requester's cache
        line = self.caches.setdefault(src_id, {}).get(address)
        if line:
            line["state"] = "SC"
            line["note"] = "Explicitly cleaned by CleanShared CMO."
        else:
            self.caches.setdefault(src_id, {})[address] = {
                "state": "SC",
                "data": self._home_line(home_id, address)["data"],
                "note": "Cleaned line inserted by CMO.",
            }

        # Update snoop filter
        entry["sharers"] = set(entry["sharers"]) | {src_id}
        entry["state_hint"] = "SharedClean"
        snooped = f" after snooping dirty owner {owner}" if owner else ""
        return f"{packet.opcode} completed{snooped}; all copies of {packet.addr} are now shared-clean."

    def _simulate_make_invalid(
        self,
        events: List[EventModel],
        packet: PacketModel,
        address: int,
        src_id: str,
        home_id: str,
        entry: Dict[str, object],
    ) -> str:
        self._send(
            events,
            channel=Channel.REQ.value,
            src="ICN0",
            dst=home_id,
            title="Invalidate routed to home",
            detail=f"ICN0 updates home node {home_id} with requester-side MakeInvalid for {packet.addr}.",
            packet=packet,
        )
        self._credit(events, src=home_id, dst="ICN0", channel=Channel.REQ.value)
        self._state(
            events,
            src=src_id,
            dst=src_id,
            title="Requester invalidated",
            detail=f"{src_id} discards its local copy of {packet.addr}; no data transfer is required.",
        )
        self._send(
            events,
            channel=Channel.RSP.value,
            src="ICN0",
            dst=src_id,
            title="Invalidate complete",
            detail=f"The dataless MakeInvalid operation for {packet.addr} is complete.",
            packet=packet.model_copy(update={"opcode": "Comp"}),
        )
        self._credit(events, src=src_id, dst="ICN0", channel=Channel.RSP.value)

        self.caches.get(src_id, {}).pop(address, None)
        entry["sharers"] = set(entry["sharers"]) - {src_id}
        if entry["owner"] == src_id:
            entry["owner"] = None
        entry["state_hint"] = "Invalid" if not entry["sharers"] and not entry["owner"] else str(entry["state_hint"])
        return f"{packet.opcode} invalidated {src_id}'s local copy of {packet.addr} with no data movement."

    def _home_for_address(self, address: int) -> str:
        for region in self.address_map:
            base = self._parse_hex(region.base)
            limit = self._parse_hex(region.limit)
            if base <= address <= limit:
                return region.node_id
        raise HTTPException(status_code=400, detail=f"Address {self._fmt_addr(address)} is unmapped.")

    def _ensure_entry(self, address: int, home_id: str) -> Dict[str, object]:
        if address not in self.snoop_filter:
            self.snoop_filter[address] = {
                "home": home_id,
                "owner": None,
                "sharers": set(),
                "state_hint": "Invalid",
                "last_opcode": "Init",
                "last_txn_id": 0,
            }
        return self.snoop_filter[address]

    def _home_line(self, home_id: str, address: int) -> Dict[str, str]:
        home_cache = self.caches.setdefault(home_id, {})
        if address not in home_cache:
            home_cache[address] = {
                "state": "UC",
                "data": "0x00000000",
                "note": f"Allocated in {home_id} by simulator.",
            }
        return home_cache[address]

    def _claim_txn_id(self) -> int:
        txn_id = self._next_txn_id
        self._next_txn_id += 1
        return txn_id

    def _send(
        self,
        events: List[EventModel],
        channel: str,
        src: str,
        dst: str,
        title: str,
        detail: str,
        packet: PacketModel,
    ) -> None:
        self._consume_credit(src, channel)
        events.append(
            EventModel(
                event_id=f"evt-{len(events) + 1}",
                title=title,
                kind="flow",
                channel=channel,
                src=src,
                dst=dst,
                detail=detail,
                packet=packet,
            )
        )

    def _state(
        self,
        events: List[EventModel],
        src: str,
        dst: str,
        title: str,
        detail: str,
    ) -> None:
        events.append(
            EventModel(
                event_id=f"evt-{len(events) + 1}",
                title=title,
                kind="state",
                channel=Channel.ACT.value,
                src=src,
                dst=dst,
                detail=detail,
            )
        )

    def _credit(self, events: List[EventModel], src: str, dst: str, channel: str) -> None:
        self.credits[dst][channel] = min(
            DEFAULT_CREDITS[channel], self.credits[dst][channel] + 1
        )
        events.append(
            EventModel(
                event_id=f"evt-{len(events) + 1}",
                title=f"{channel} credit return",
                kind="credit",
                channel=Channel.CRD.value,
                src=src,
                dst=dst,
                detail=f"{src} returns one {channel} credit to {dst}.",
                related_channel=channel,
            )
        )

    def _consume_credit(self, node_id: str, channel: str) -> None:
        if channel not in self.credits.get(node_id, {}):
            return
        self.credits[node_id][channel] = max(0, self.credits[node_id][channel] - 1)

    def _parse_hex(self, value: str) -> int:
        try:
            return int(value, 0)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid hex value {value}") from exc

    def _fmt_addr(self, value: int) -> str:
        return f"0x{value:04X}"

    def _format_sharers(self, sharers: object) -> str:
        if not sharers:
            return "none"
        return ", ".join(sorted(str(item) for item in set(sharers)))


SIMULATOR = Simulator()
