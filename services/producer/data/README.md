# Producer datasets

This directory is bind-mounted into the producer container at `/app/data`.

## Bundled sample

`sample_comments.csv` ships with the repo. It follows the Jigsaw schema
(`id, comment_text, toxic, severe_toxic, obscene, threat, insult, identity_hate`)
but the comments are synthetic — written for this project, not extracted from
the real dataset. It exists so the producer boots out of the box without any
external download.

## Using the real Jigsaw dataset

1. Download `train.csv` from the [Jigsaw Toxic Comment Classification Challenge](https://www.kaggle.com/c/jigsaw-toxic-comment-classification-challenge/data).
2. Drop it under `services/producer/data/jigsaw/train.csv` (already gitignored).
3. Point the producer at it:

   ```bash
   DATASET_PATH=/app/data/jigsaw/train.csv docker compose up producer
   ```

The CSV schema must contain at minimum `id` and `comment_text`; the six label
columns are read when present and ignored when absent.
