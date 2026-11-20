Run from terminal:

source .venv/bin/activate
python try_client.py


Run the evals:

To run it:
source .venv/bin/activate
pip install -r evals/requirements.txt
# add ANTHROPIC_API_KEY=... to .env
python evals/run_evals.py                 # 1 attempt per case
python evals/run_evals.py --reps 3        # 3 attempts per case: pass rates are noisy
python evals/run_evals.py --variant v1    # after a tool change, to compare against baseline
A single attempt should cost a few cents. The summary prints the measured total.