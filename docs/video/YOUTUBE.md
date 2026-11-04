# Uploading the demo video

**File:** `docs/video/datatrace-demo.mp4` (2:52, 1920x1080). **Captions:** `docs/demo_captions.srt`.

1. YouTube → Create → Upload video → choose the file. Visibility: **Unlisted**.
2. Paste the title and description below. YouTube turns the timestamps into chapters.
3. Optional: Subtitles → Add language → English → Upload file → *With timing* → `docs/demo_captions.srt`
   (captions are already burned into the video; this adds a searchable, toggleable track).
4. Open the link in a private window to check it plays, then paste it into the submission form.

**Title**

DataTrace: is the claims jump real, or is the dashboard wrong? (Meta Muse Spark agent)

**Description**

DataTrace is an agent that tells a healthcare finance team whether a jump in paid claims is real or a data defect, and proves it with verified SQL. Built for the Meta Global AI Developer Hackathon 2026 (Indie Developer · Build for Your World).

• Muse Spark (muse-spark-1.3) investigates with sandboxed, read-only SQL and never sees raw rows
• Muse Wonder (muse-wonder-1.0) independently reviews every diagnosis and caught 28/28 planted errors
• Muse Voice Transcribe turns an actuary's voice note into the request
• On CMS claims: right dollar split in 16/16 runs vs. 4/16 for the same model reading every raw row

Code: https://github.com/musharraf3/DataTrace

0:00 The 8 a.m. question
0:14 What DataTrace is
0:27 Voice note + screenshot intake
0:43 The agent investigates
1:11 Verdict: real run-out vs. reporting error
1:39 It asks instead of guessing
1:56 Benchmark: agent vs. raw rows
2:18 Reviewer stress test
2:31 How it works

All screens are the real app making live Meta API calls; model waiting time is trimmed or sped up as labelled on screen. Narration is a synthetic voice. Data: CMS 2008–2010 DE-SynPUF synthetic Medicare claims (public domain, no real patients); claims lag, reversals and the defect are simulated.
