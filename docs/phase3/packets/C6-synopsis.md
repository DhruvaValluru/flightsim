# C6 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T15:59:05Z

## C6 verify: pytest -q -k component

- log: `runs/p3/A-2/C6-pytest.log`
- exit: 0 (expected 0) -> PASS

```
...........................                                              [100%]
============================== warnings summary ===============================
tests/test_annotation_gates.py: 12 warnings
tests/test_dataset_boxes.py: 6 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:384: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(ids, mode="L").save(folder / f"{stem}_mask.png")

tests/test_annotation_gates.py: 12 warnings
tests/test_dataset_boxes.py: 6 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:385: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(classes, mode="L").save(folder / f"{stem}_class.png")

tests/test_annotation_gates.py: 12 warnings
tests/test_dataset_boxes.py: 6 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:389: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(png.astype(np.uint16), mode="I;16").save(folder / f"{stem}_depth.png")

tests/test_annotation_gates.py: 30 warnings
tests/test_dataset_boxes.py: 18 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:404: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(alone, mode="L").save(folder / alone_name)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

## C6 COCO half: pytest -v tests/test_dataset_boxes.py -k payload_and_gear_are_their_own_coco

- log: `runs/p3/A-2/C6-coco.log`
- exit: 0 (expected 0) -> PASS

```
timeout method: thread
timeout func_only: False
collected 13 items / 12 deselected / 1 selected

tests\test_dataset_boxes.py .                                            [100%]

============================== warnings summary ===============================
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:384: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(ids, mode="L").save(folder / f"{stem}_mask.png")

tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:385: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(classes, mode="L").save(folder / f"{stem}_class.png")

tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:389: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(png.astype(np.uint16), mode="I;16").save(folder / f"{stem}_depth.png")

tests/test_dataset_boxes.py: 18 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:404: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(alone, mode="L").save(folder / alone_name)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 1 passed, 12 deselected, 36 warnings in 6.78s ================
```

note: run A-2 on 23bad766; 55 component tests, no F; mutant half is the Mac auditor's (state/A.json audit)

## verdict

PASS
