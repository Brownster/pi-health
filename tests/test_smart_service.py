"""Tests for framework-neutral SMART operations."""

from unittest.mock import Mock, call

import pytest

from smart_service import SmartOperationError, SmartService, SmartValidationError


def service(*, helper=None, parser=None):
    return SmartService(
        helper=helper if helper is not None else Mock(),
        parser=parser if parser is not None else Mock(),
    )


def parsed(data):
    result = Mock()
    result.to_dict.return_value = {"parsed": data["device"]["name"]}
    return result


def test_all_devices_parses_data_and_preserves_per_device_error():
    helper = Mock()
    helper.call.return_value = {
        "success": True,
        "devices": [
            {"device": "/dev/sda", "data": {"device": {"name": "/dev/sda"}}},
            {"device": "/dev/sdb", "error": "unsupported"},
        ],
    }
    parser = Mock(side_effect=parsed)

    result = service(helper=helper, parser=parser).all_devices()

    assert result == {
        "disks": [
            {"device": "/dev/sda", "data": {"parsed": "/dev/sda"}},
            {
                "device": "/dev/sdb",
                "data": {"device": "/dev/sdb", "error_message": "unsupported"},
            },
        ]
    }
    parser.assert_called_once_with({"device": {"name": "/dev/sda"}})


def test_all_devices_maps_helper_rejection():
    helper = Mock()
    helper.call.return_value = {"success": False, "error": "smartctl missing"}

    with pytest.raises(SmartOperationError, match="smartctl missing"):
        service(helper=helper).all_devices()


def test_device_validates_name_before_helper_call():
    helper = Mock()

    with pytest.raises(SmartValidationError, match="Invalid device name"):
        service(helper=helper).device("sda;rm")

    helper.call.assert_not_called()


def test_device_passes_sat_and_parses_result():
    helper = Mock()
    raw = {"device": {"name": "/dev/sda"}}
    helper.call.return_value = {"success": True, "data": raw}
    parser = Mock(side_effect=parsed)

    result = service(helper=helper, parser=parser).device("sda", use_sat=True)

    assert result == {"parsed": "/dev/sda"}
    helper.call.assert_called_once_with(
        "smart_info", {"device": "/dev/sda", "use_sat": True}
    )


@pytest.mark.parametrize("test_type", ["short", "long", "conveyance"])
def test_start_test_preserves_supported_types(test_type):
    helper = Mock()
    helper.call.return_value = {"success": True, "message": "started"}

    result = service(helper=helper).start_test(
        "nvme0n1", test_type=test_type, use_sat=True
    )

    assert result == {
        "status": "started",
        "test_type": test_type,
        "message": "started",
    }
    assert helper.call.call_args_list == [
        call(
            "smart_test",
            {
                "device": "/dev/nvme0n1",
                "test_type": test_type,
                "use_sat": True,
            },
        )
    ]


def test_start_test_rejects_unknown_type_before_helper_call():
    helper = Mock()

    with pytest.raises(SmartValidationError, match="Invalid test type"):
        service(helper=helper).start_test("sda", test_type="destructive")

    helper.call.assert_not_called()


def test_start_test_maps_helper_rejection():
    helper = Mock()
    helper.call.return_value = {"success": False, "error": "device busy"}

    with pytest.raises(SmartOperationError, match="device busy"):
        service(helper=helper).start_test("sda")
