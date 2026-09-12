# six-chunk configuration audit

## validated_from_whale_chunk6

Historical Whale scripts declare `mpi`, 384 ranks, `span[ptile=64]`, six nodes via `ppr:64:node`, GCC 12.4/OpenMPI 4.1.5 and an LSF hostfile launcher. The uploaded directory contains no job log; historical success is user-supplied evidence.

## validated_from_existing_6chunk_test

The existing PREM six-chunk fixture logged 384 ranks, NEX 448x448, NPROC 8x8 and DT=0.1.

## common_frozen_settings

NCHUNKS=6; NEX=448x448; NPROC=8x8; 384 ranks; ptile64; attenuation true; absorbing false.

## remaining_unverified_settings

This package changes OCEANS to false and combines PREM/ASDF with the fixed multi-ULVZ source baseline and Whale OpenMPI build. Those are deployment-time validation items.
