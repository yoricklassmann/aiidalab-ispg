# ruff: noqa: INP001
import requests
from enum import Enum
from pathlib import Path

import pytest

# https://selenium-python.readthedocs.io/locating-elements.html
import selenium.webdriver.support.expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.by import By

WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 1450


# Copied over from aiidalab_widgets_base/wizard.py
class StepState(Enum):
    """Wizzard step state"""

    INIT = 0  # the step is initialized and all widgets are typically disabled
    CONFIGURED = 1  # configuration is valid
    READY = 2  # step is ready for user input
    ACTIVE = 3  # step is carrying out a runtime operation
    SUCCESS = 4  # step has successfully completed
    FAIL = -1  # the step has unrecoverably failed


@pytest.fixture()
def check_step_status(selenium):
    ICONS = {
        StepState.INIT: "○",
        StepState.READY: "◎",
        StepState.CONFIGURED: "●",
        StepState.SUCCESS: "✓",
        StepState.FAIL: "×",  # noqa: RUF001
        # The ACTIVE state is "animated", see aiidalab_widgets_base/wizard.py,
        # hence we cannot use it in tests.
        # WizardAppWidgetStep.State.ACTIVE: ["\u25dc", "\u25dd", "\u25de", "\u25df"],
    }

    def _check_step_status(step_num, expected_state: StepState):
        icon = ICONS[expected_state]
        selenium.find_element(
            By.XPATH, f"//span[starts-with(.,'{icon} Step {step_num}')]"
        )

    return _check_step_status


@pytest.mark.tryfirst()
def test_post_install(notebook_service, aiidalab_exec, nb_user, appdir):
    aiidalab_exec("./post_install", workdir=appdir, user=nb_user)


def test_notebook_service_available(notebook_service):
    url, token = notebook_service
    response = requests.get(f"{url}/?token={token}", timeout=100)
    assert response.status_code == 200


def test_dependencies(notebook_service, aiidalab_exec, nb_user):
    aiidalab_exec("pip check", user=nb_user)


def test_conformer_generation_init(selenium_driver, final_screenshot):
    driver = selenium_driver("conformer_generation.ipynb", wait_time=30.0)
    driver.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
    driver.find_element(By.XPATH, "//button[text()='Generate molecule']")


def test_conformer_generation_steps(
    selenium_driver, final_screenshot, generate_mol_from_smiles, check_atoms
):
    driver = selenium_driver("conformer_generation.ipynb", wait_time=30.0)
    driver.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)

    # Generate methane molecule
    generate_mol_from_smiles("C")

    # Switch to Selection tab
    selection = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//*[text()='Selection']"))
    )
    selection.click()
    # Select atoms and verify them
    # TODO: Firefox seems to fail for atoms beyond the first one,
    # so we just check the first one for now
    # check_atoms("CHHHH")
    check_atoms("C")

    # Test different generation options
    driver.find_element(By.XPATH, "//option[@value='UFF']").click()
    driver.find_element(By.XPATH, "//option[@value='ETKDGv1']").click()
    generate_mol_from_smiles("N")
    check_atoms("N")

    driver.find_element(By.XPATH, "//option[@value='MMFF94s']").click()
    driver.find_element(By.XPATH, "//option[@value='ETKDGv2']").click()
    generate_mol_from_smiles("O")
    check_atoms("O")

    # Switch to `Download` tab in StructureDataViewer
    driver.find_element(By.XPATH, "//*[text()='Download']").click()
    download = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//button[text()='Download']"))
    )
    download.click()


def test_optimization_init(
    selenium_driver, final_screenshot, button_disabled, check_step_status
):
    driver = selenium_driver("optimization.ipynb", wait_time=30.0)
    driver.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
    driver.find_element(By.XPATH, "//button[text()='Generate molecule']")
    check_step_status(1, StepState.READY)
    check_step_status(2, StepState.INIT)
    check_step_status(3, StepState.INIT)
    button_disabled("Confirm")
    button_disabled("Submit")


def test_optimization_steps(
    selenium_driver,
    final_screenshot,
    button_enabled,
    button_disabled,
    generate_mol_from_smiles,
    check_atoms,
    check_step_status,
):
    driver = selenium_driver("optimization.ipynb", wait_time=30.0)
    driver.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)

    check_step_status(1, StepState.READY)
    check_step_status(2, StepState.INIT)
    check_step_status(3, StepState.INIT)
    button_disabled("Confirm")
    button_disabled("Submit")

    driver.find_element(By.XPATH, "//button[text()='Generate molecule']")
    # Generate methane molecule
    generate_mol_from_smiles("C")
    driver.find_element(By.XPATH, "//*[text()='Selection']").click()
    check_atoms("C")

    check_step_status(1, StepState.CONFIGURED)
    button_enabled("Confirm")
    driver.find_element(By.XPATH, "//button[text()='Confirm']").click()

    # Test that we have indeed proceeded to the next step
    check_step_status(1, StepState.SUCCESS)
    # NOTE: In CI we do not have ORCA, so the step state is not CONFIGURED
    # check_step_status(2, StepState.CONFIGURED)
    check_step_status(2, StepState.READY)
    check_step_status(3, StepState.INIT)

    button_disabled("Confirm")
    button_disabled("Submit")
    WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.XPATH, "//button[text()='Submit']"))
    )


def test_spectrum_app_init(selenium_driver, final_screenshot):
    driver = selenium_driver("spectrum_widget.ipynb", wait_time=30.0)
    driver.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
    driver.find_element(By.XPATH, "//button[text()='Download spectrum']")


def test_atmospec_app_init(selenium_driver, final_screenshot, check_step_status):
    driver = selenium_driver("atmospec.ipynb", wait_time=30.0)
    driver.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
    check_step_status(1, StepState.READY)
    check_step_status(2, StepState.INIT)
    check_step_status(3, StepState.INIT)
    check_step_status(4, StepState.INIT)
    driver.find_element(By.XPATH, "//button[text()='Refresh']")


def test_atmospec_steps(
    selenium_driver,
    screenshot_dir,
    final_screenshot,
    button_enabled,
    button_disabled,
    generate_mol_from_smiles,
    check_atoms,
    check_step_status,
):
    driver = selenium_driver("atmospec.ipynb", wait_time=40.0)
    driver.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)

    check_step_status(1, StepState.READY)
    # Because we don't have a structure yet, the confirm button should be disabled
    button_disabled("Confirm")
    button_disabled("Submit")

    # Generate methane molecule
    generate_mol_from_smiles("C")
    check_atoms("C")
    driver.get_screenshot_as_file(
        Path.joinpath(screenshot_dir, "atmospec-steps-mol-generated.png")
    )
    check_step_status(1, StepState.CONFIGURED)

    # Confirm structure and go to the next step
    button_enabled("Confirm")
    button_disabled("Submit")
    WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.XPATH, "//button[text()='Confirm']"))
    ).click()

    # Once the structure is confirmed, the button should be disabled
    button_disabled("Confirm")

    check_step_status(1, StepState.SUCCESS)
    check_step_status(2, StepState.READY)
    check_step_status(3, StepState.INIT)
    check_step_status(4, StepState.INIT)

    # Make sure the submit button is visible. It should not be clickable since
    # ORCA is not installed.
    WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.XPATH, "//button[text()='Submit']"))
    )
    button_disabled("Submit")
