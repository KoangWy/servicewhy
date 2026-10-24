"""ServiceWhy entry point (Technical Execution Guide §2).

  python run.py                                  # serve the API on 0.0.0.0:$PORT
  python run.py ask "Why did Saturday dinner revenue drop 18%?"   # one investigation, JSON to stdout
"""
import json
import sys

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "ask":
        from app.config import Settings, load_dotenv
        load_dotenv()
        settings = Settings.from_env()
        if settings.sample_mode:
            from app.sample import SampleStore
            print(json.dumps(SampleStore(settings.sample_dir).run(" ".join(sys.argv[2:])), indent=2))
        else:
            from app.runtime import orchestrator
            print(json.dumps(orchestrator(settings).run(" ".join(sys.argv[2:])), indent=2, default=str))
    else:
        from app.run import main
        main()
