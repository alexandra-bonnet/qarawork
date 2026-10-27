# Contributing

QARAWORK is a collection of early-stage open-source prototypes for regulated software workflows.

Before submitting a change, open an issue describing the problem or proposed feature, without confidential information. Keep examples generic and use synthetic data only.

Run the tests for any package you modify:

```bash
python -m pip install -e "./tools/traceability[dev]"
python -m pytest tools/traceability/tests -q
```

Replace `traceability` with the affected tool. Keep automated checks independent of live service credentials.

A contribution does not imply that the changed implementation is validated for regulated use. Reviews and approvals remain the responsibility of each adopting organization.
