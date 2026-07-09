from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class NodeKind(str, Enum):
    RN = "RN"
    ICN = "ICN"
    SN = "SN"


class Channel(str, Enum):
    REQ = "REQ"
    SNP = "SNP"
    RSP = "RSP"
    DAT = "DAT"
    CRD = "CRD"
    ACT = "ACT"


class Opcode(str, Enum):
    READ_NO_SNP = "ReadNoSnp"
    READ_ONCE = "ReadOnce"
    READ_CLEAN = "ReadClean"
    READ_SHARED = "ReadShared"
    READ_UNIQUE = "ReadUnique"
    READ_PREFER_UNIQUE = "ReadPreferUnique"
    WRITE_NO_SNP_FULL = "WriteNoSnpFull"
    WRITE_UNIQUE = "WriteUnique"
    WRITE_BACK_FULL = "WriteBackFull"
    WRITE_CLEAN_FULL = "WriteCleanFull"
    WRITE_EVICT_FULL = "WriteEvictFull"
    CLEAN_UNIQUE = "CleanUnique"
    MAKE_UNIQUE = "MakeUnique"
    CLEAN_SHARED = "CleanShared"
    CLEAN_INVALID = "CleanInvalid"
    MAKE_INVALID = "MakeInvalid"


class NodeModel(BaseModel):
    node_id: str
    label: str
    kind: NodeKind
    color: str
    x: int
    y: int
    description: str


class LinkModel(BaseModel):
    src: str
    dst: str
    label: str


class AddressRegionModel(BaseModel):
    region_id: str
    node_id: str
    label: str
    base: str
    limit: str
    color: str


class CacheLineModel(BaseModel):
    address: str
    state: str
    data: str
    note: str


class SnoopFilterEntryModel(BaseModel):
    address: str
    home: str
    owner: Optional[str] = None
    sharers: List[str] = Field(default_factory=list)
    state_hint: str
    last_opcode: str
    last_txn_id: int


class PacketModel(BaseModel):
    opcode: str
    srcid: str
    tgtid: str
    txnid: int
    addr: str
    size: int
    qos: int
    ns: bool
    attributes: Dict[str, Any] = Field(default_factory=dict)
    payload: Optional[str] = None


class EventModel(BaseModel):
    event_id: str
    title: str
    kind: Literal["flow", "state", "credit"]
    channel: str
    src: str
    dst: str
    detail: str
    related_channel: Optional[str] = None
    packet: Optional[PacketModel] = None


class HistoryEntryModel(BaseModel):
    txnid: int
    opcode: str
    srcid: str
    tgtid: str
    addr: str
    summary: str
    issued_at: str


class SimulationSnapshotModel(BaseModel):
    nodes: List[NodeModel]
    links: List[LinkModel]
    address_map: List[AddressRegionModel]
    caches: Dict[str, List[CacheLineModel]]
    snoop_filter: List[SnoopFilterEntryModel]
    credits: Dict[str, Dict[str, int]]
    history: List[HistoryEntryModel] = Field(default_factory=list)
    next_txn_id: int = 17


class SimulationResultModel(BaseModel):
    transaction: PacketModel
    events: List[EventModel]
    snapshot: SimulationSnapshotModel
    summary: str


class ClientStateModel(BaseModel):
    """Portable simulator state sent by the client for stateless deployments."""
    caches: Dict[str, List[CacheLineModel]]
    snoop_filter: List[SnoopFilterEntryModel]
    credits: Dict[str, Dict[str, int]]
    history: List[HistoryEntryModel] = Field(default_factory=list)
    next_txn_id: int = 17


class TransactionRequestModel(BaseModel):
    opcode: Opcode
    src_id: str
    address: str
    tgt_id: Optional[str] = None
    txn_id: Optional[int] = None
    size: int = 64
    qos: int = 2
    ns: bool = False
    data: Optional[str] = None
    # Client-side state for stateless deployment
    client_state: Optional[ClientStateModel] = None


class NodePositionModel(BaseModel):
    node_id: str
    x: int = Field(ge=40, le=1400)
    y: int = Field(ge=40, le=1000)


class LayoutUpdateModel(BaseModel):
    positions: List[NodePositionModel]


class AddressRegionUpdateModel(BaseModel):
    region_id: str
    base: str
    limit: str


class AddressMapUpdateModel(BaseModel):
    regions: List[AddressRegionUpdateModel]
