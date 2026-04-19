# Tone samples

Drop your own tweets into this folder as `.txt` files. The generator reads every `*.txt` file here and feeds them to Claude as style examples.

## How to add

- Create one or many `.txt` files. Any filename works.
- One tweet per file, or many tweets separated by blank lines — both work.
- **Don't** paste URLs, retweet markers, or reply `@mentions` you don't want mimicked.
- Aim for 50–200 of your own tweets for best results. 20 will work but will leak the default voice more.

## Tip: exporting from X

1. Your Twitter archive (`Settings → Your Account → Download an archive of your data`) contains `data/tweets.js`. A quick script can filter out replies/RTs and dump just your original tweet text.
2. Or copy/paste your best 100 tweets by hand — curation > volume.

## What the generator does

Without samples: falls back to a generic "punchy, specific, no hashtags" style.

With samples: prompt becomes "mimic this user's voice, cadence, and punctuation" and Claude uses the samples as a few-shot example.
