import io

from binascii import hexlify
from struct import unpack
from typing import List, TypeVar, Callable


def read_compact_size(stream: io.BytesIO, what: str = "") -> int:
    n, = unpack("<B", stream.read(1))
    if n < 253:
        ret = n
    elif n == 253:
        ret, = unpack("<H", stream.read(2))
        assert ret >= 253
    elif n == 254:
        ret, = unpack("<I", stream.read(4))
        assert ret >= 0x10000
    else:
        ret, = unpack("<Q", stream.read(8))
        assert ret >= 0x100000000

    assert ret <= 0x02000000
    return ret


T = TypeVar("T")


def read_vector(
    stream: io.BytesIO, read_elem: Callable[[io.BytesIO], T], what: str = "vector"
) -> List[T]:
    n = read_compact_size(stream, what)
    ret: List[T] = []

    for i in range(0, n):
        ret.append(read_elem(stream))

    return ret


def read_bytes(stream: io.BytesIO, what: str = "bytes") -> bytes:
    n = read_compact_size(stream, what)
    return stream.read(n)


class OutPoint(object):
    def __init__(self, hash: bytes, n: int) -> None:
        self.hash = hash
        self.n = n

    def __repr__(self) -> str:
        return f"{hexlify(bytes(reversed(self.hash)))}:{self.n}"

    @classmethod
    def from_bytes(cls, stream: io.BytesIO):
        hash = stream.read(32)
        n, = unpack("<I", stream.read(4))

        return OutPoint(hash, n)


class TxIn(object):
    def __init__(self, prevout, script_sig, sequence):
        self.prevout = prevout
        self.script_sig = script_sig
        self.sequence = sequence

    @classmethod
    def from_bytes(cls, stream: io.BytesIO):
        prevout = OutPoint.from_bytes(stream)
        sig = read_bytes(stream, "ScriptSig")
        sn, = unpack("<I", stream.read(4))

        return TxIn(prevout, sig, sn)


class TxOut(object):
    def __init__(self, value: int, pubkey: bytes) -> None:
        self.value = value
        self.pubkey = pubkey

    @classmethod
    def from_bytes(cls, stream: io.BytesIO):
        value, = unpack("<Q", stream.read(8))
        pubkey = read_bytes(stream)
        return TxOut(value, pubkey)


class JoinSplit(object):
    def __init__(
        self,
        vpub_old,
        vpub_new,
        anchor,
        nullifiers,
        commitments,
        ephemeral_key,
        random_seed,
        macs,
        proof,
        ciphertexts,
    ) -> None:
        self.vpub_old = vpub_old
        self.vpub_new = vpub_new
        self.anchor = anchor
        self.nullifiers = nullifiers
        self.commitments = commitments
        self.ephemeral_key = ephemeral_key
        self.random_seed = random_seed
        self.macs = macs
        self.proof = proof
        self.ciphertexts = ciphertexts

    @classmethod
    def from_bytes(cls, stream: io.BytesIO):
        vpub_old, = unpack("<Q", stream.read(8))
        vpub_new, = unpack("<Q", stream.read(8))

        anchor = stream.read(32)
        nullifiers = [stream.read(32) for i in range(0, 2)]
        commitments = [stream.read(32) for i in range(0, 2)]

        ephemeral_key = stream.read(32)
        random_seed = stream.read(32)
        macs = [stream.read(32) for i in range(0, 2)]

        proof = [
            [stream.read(1), stream.read(32)],
            [stream.read(1), stream.read(32)],
            [stream.read(1), stream.read(64)],
            [stream.read(1), stream.read(32)],
            [stream.read(1), stream.read(32)],
            [stream.read(1), stream.read(32)],
            [stream.read(1), stream.read(32)],
            [stream.read(1), stream.read(32)],
        ]

        ciphertexts = [stream.read(585 + 16) for i in range(0, 2)]

        return JoinSplit(
            vpub_old,
            vpub_new,
            anchor,
            nullifiers,
            commitments,
            ephemeral_key,
            random_seed,
            macs,
            proof,
            ciphertexts,
        )


class Transaction(object):
    def __init__(
        self, version, vin, vout, lock_time, vjoinsplit, joinsplit_pubkey, joinsplit_sig
    ):
        self.version = version
        self.vin = vin
        self.vout = vout
        self.lock_time = lock_time
        self.vjoinsplit = vjoinsplit
        self.joinsplit_pubkey = joinsplit_pubkey
        self.joinsplit_sig = joinsplit_sig

    @classmethod
    def from_bytes(cls, stream: io.BytesIO):
        version, = unpack("<I", stream.read(4))

        vin = read_vector(stream, TxIn.from_bytes, "TxIn")
        vout = read_vector(stream, TxOut.from_bytes, "TxOut")
        locktime, = unpack("<I", stream.read(4))
        if version >= 2:
            joinsplits = read_vector(stream, JoinSplit.from_bytes, "JoinSplit")
        else:
            joinsplits = []

        if len(joinsplits) > 0:
            joinsplit_pubkey = stream.read(32)
            joinsplit_sig = stream.read(64)
        else:
            joinsplit_pubkey = b""
            joinsplit_sig = b""

        return Transaction(
            version, vin, vout, locktime, joinsplits, joinsplit_pubkey, joinsplit_sig
        )


class BlockHeader(object):
    def __init__(
        self, version, hash_prev, hash_root, hash_extra, time, bits, nonce, solution
    ):
        self.version = version
        self.hash_prev = hash_prev
        self.hash_root = hash_root
        self.hash_extra = hash_extra
        self.time = time
        self.bits = bits
        self.nonce = nonce
        self.solution = solution

    @classmethod
    def from_bytes(cls, stream: io.BytesIO):
        version = stream.read(4)
        hash_prev = stream.read(32)
        hash_root = stream.read(32)
        hash_extra = stream.read(32)
        time = stream.read(4)
        bits = stream.read(4)
        nonce = stream.read(32)

        solution = read_bytes(stream, "solution")

        return BlockHeader(
            version, hash_prev, hash_root, hash_extra, time, bits, nonce, solution
        )


class Block(object):
    def __init__(self, header, transactions):
        self.header = header
        self.transactions = transactions

    @classmethod
    def from_bytes(cls, stream: io.BytesIO):

        header = BlockHeader.from_bytes(stream)
        transactions = read_vector(stream, Transaction.from_bytes, "Transaction")

        return Block(header, transactions)


def read_blockfile(name: str, expected_prefix: bytes) -> List[Block]:
    ret = []
    with open(name, "rb") as f:

        magic = f.read(len(expected_prefix))
        while len(magic):
            assert magic == expected_prefix

            size, = unpack("<I", f.read(4))
            raw_block = io.BytesIO(f.read(size))
            ret.append(Block.from_bytes(raw_block))

            magic = f.read(len(expected_prefix))

    return ret