"""Steps specific for the optimization workflow"""

import enum
from dataclasses import dataclass

import ipywidgets as ipw
from IPython.display import clear_output, display
import traitlets

from aiida.engine import submit, ProcessState
from aiida.orm import Bool
from aiida.orm import load_code, load_node
from aiida.plugins import WorkflowFactory


from .input_widgets import (
    ResourceSelectionWidget,
    CodeSettings,
    MoleculeSettings,
    GroundStateSettings,
)
from .utils import MEMORY_PER_CPU
from .widgets import TrajectoryDataViewer, spinner
from .steps import SubmitWorkChainStepBase, ViewWorkChainStatusStep

ConformerOptimizationWorkChain = WorkflowFactory("ispg.conformer_opt")


@dataclass(frozen=True)
class OptimizationParameters:
    charge: int
    multiplicity: int
    method: str
    basis: str
    solvent: str


DEFAULT_OPTIMIZATION_PARAMETERS = OptimizationParameters(
    charge=0,
    multiplicity=1,
    method="wB97X-D4",
    basis="aug-cc-pVDZ",
    solvent="None",
)


class SubmitOptimizationWorkChainStep(SubmitWorkChainStepBase):
    """Step for submission of a optimization workchain."""

    def __init__(self, **kwargs):
        self.molecule_settings = MoleculeSettings()
        self.ground_state_settings = GroundStateSettings()
        self.code_settings = CodeSettings()
        self.resources_settings = ResourceSelectionWidget()

        # We need to observe each widget for which the validation could fail.
        self.code_settings.orca.observe(self._update_state, "value")

        grid = ipw.GridBox(
            [
                self.molecule_settings,
                self.ground_state_settings,
                self.code_settings,
                self.resources_settings,
            ],
            layout=ipw.Layout(
                width="100%",
                grid_gap="0% 5%",
                grid_template_rows="auto auto",
                grid_template_columns="47% 47%",
            ),
        )
        self._update_ui_from_parameters(DEFAULT_OPTIMIZATION_PARAMETERS)
        super().__init__(components=[grid])

    # TODO: More validations (molecule size etc)
    # TODO: display an error message when there is an issue.
    # See how "submission blockers" are handled in QeApp
    def _validate_input_parameters(self) -> bool:
        """Validate input parameters"""
        # ORCA code not selected.
        if self.code_settings.orca.value is None:
            return False
        return True

    def _update_ui_from_parameters(self, parameters: OptimizationParameters) -> None:
        """Update UI widgets according to builder parameters.

        This function is called when we load an already finished workflow,
        and we want the input widgets to be updated accordingly
        """
        self.molecule_settings.charge.value = parameters.charge
        self.molecule_settings.multiplicity.value = parameters.multiplicity
        self.molecule_settings.solvent.value = parameters.solvent
        self.ground_state_settings.method.value = parameters.method
        self.ground_state_settings.basis.value = parameters.basis

    def _get_parameters_from_ui(self) -> OptimizationParameters:
        """Prepare builder parameters from the UI input widgets"""
        return OptimizationParameters(
            charge=self.molecule_settings.charge.value,
            multiplicity=self.molecule_settings.multiplicity.value,
            solvent=self.molecule_settings.solvent.value,
            method=self.ground_state_settings.method.value,
            basis=self.ground_state_settings.basis.value,
        )

    @traitlets.observe("process")
    def _observe_process(self, change):
        with self.hold_trait_notifications():
            self.header_warning.hide()
            process = change["new"]
            if process is not None:
                self.input_structure = process.inputs.structure
                try:
                    parameters = process.base.extras.get("builder_parameters")
                    self._update_ui_from_parameters(
                        OptimizationParameters(**parameters)
                    )
                except (AttributeError, KeyError, TypeError):
                    # extras do not exist or are incompatible, ignore this problem
                    self.header_warning.show(
                        f"WARNING: Workflow parameters could not be loaded from process pk: {process.pk}"
                    )
            self._update_state()

    def submit(self, _=None):
        assert self.input_structure is not None

        parameters = self._get_parameters_from_ui()
        builder = ConformerOptimizationWorkChain.get_builder()

        builder.structure = self.input_structure
        builder.orca.code = load_code(self.code_settings.orca.value)

        num_mpiprocs = self.resources_settings.num_mpi_tasks.value
        builder.orca.metadata = self._build_orca_metadata(num_mpiprocs)
        builder.orca.parameters = self._build_orca_params(parameters)
        if num_mpiprocs > 1:
            builder.orca.parameters["input_blocks"]["pal"] = {"nproc": num_mpiprocs}

        # Clean the remote directory by default,
        # We're copying back the main output file and gbw file anyway.
        builder.clean_workdir = Bool(True)

        process = submit(builder)

        # NOTE: It is important to set_extra builder_parameters before we update the traitlet
        process.base.extras.set("builder_parameters", vars(parameters))
        self.process = process

    # TODO: Need to implement logic for handling more CPUs
    # and distribute them among conformers
    def _build_orca_metadata(self, num_mpiprocs: int):
        return {
            "options": {
                "withmpi": False,
                "resources": {
                    "tot_num_mpiprocs": num_mpiprocs,
                    "num_mpiprocs_per_machine": num_mpiprocs,
                    "num_cores_per_mpiproc": 1,
                    "num_machines": 1,
                },
            }
        }

    def _build_orca_params(self, params: OptimizationParameters) -> dict:
        """Prepare dictionary of ORCA parameters, as required by aiida-orca plugin"""
        input_keywords = [params.basis, params.method, "Opt", "AnFreq"]
        input_blocks = {
            "scf": {"convergence": "tight", "ConvForced": "true"},
        }

        # WARNING: Here we implicitly assume, that ORCA will automatically select
        # equilibrium solvation for ground state optimization,
        # and non-equilibrium solvation for single point excited state calculations.
        # This should be the default, but it would be better to be explicit.
        if params.solvent != "None":
            input_keywords.append(f"CPCM({params.solvent})")

        # For MP2, analytical frequencies are only available without Frozen Core
        if params.method.lower() in ("ri-mp2", "mp2"):
            input_keywords.append("NoFrozenCore")
            input_keywords.append(f"{params.basis}/C")
            input_blocks["mp2"] = {"maxcore": MEMORY_PER_CPU}

        return {
            "charge": params.charge,
            "multiplicity": params.multiplicity,
            "input_blocks": input_blocks,
            "input_keywords": input_keywords,
        }


class OptimizationWorkflowStatus(enum.Enum):
    INIT = 0
    IN_PROGRESS = 1
    FINISHED = 2
    FAILED = 3


class OptimizationWorkflowProgressWidget(ipw.HBox):
    """Widget for user friendly representation of the workflow status."""

    status = traitlets.Instance(OptimizationWorkflowStatus, allow_none=True)

    def __init__(self, **kwargs):
        self._progress_bar = ipw.IntProgress(
            style={"description_width": "initial"},
            description="Workflow progress:",
            value=0,
            min=0,
            max=2,
            disabled=False,
            orientations="horizontal",
        )

        self._status_text = ipw.HTML()
        super().__init__([self._progress_bar, self._status_text], **kwargs)

    @traitlets.observe("status")
    def _observe_status(self, change):
        with self.hold_trait_notifications():
            if change["new"]:
                self._status_text.value = {
                    OptimizationWorkflowStatus.INIT: "Workflow started",
                    OptimizationWorkflowStatus.IN_PROGRESS: f"Optimizing conformers {spinner}",
                    OptimizationWorkflowStatus.FINISHED: "Worflow finished successfully! 🎉",
                    OptimizationWorkflowStatus.FAILED: "Workflow failed! 😧",
                }.get(change["new"], change["new"].name)

                self._progress_bar.value = change["new"].value
                self._progress_bar.bar_style = {
                    OptimizationWorkflowStatus.FINISHED: "success",
                    OptimizationWorkflowStatus.FAILED: "danger",
                }.get(change["new"], "info")
            else:
                self._status_text.value = ""
                self._progress_bar.value = 0
                self._progress_bar.bar_style = "info"


class ViewOptimizationStatusAndResultsStep(ViewWorkChainStatusStep):
    """Widget for displaying the whole workflow as it runs"""

    workflow_status = traitlets.Instance(OptimizationWorkflowStatus, allow_none=True)

    def __init__(self, **kwargs):
        self.progress_bar = OptimizationWorkflowProgressWidget()
        ipw.dlink(
            (self, "workflow_status"),
            (self.progress_bar, "status"),
        )

        title = ipw.HTML(
            """<div style="padding-top: 0px; padding-bottom: 0px">
            <h4>Optimized Structures</h4>
        </div>""",
        )
        self.relaxed_structures = ipw.Output()

        self.results = ipw.VBox([title, self.relaxed_structures])
        self.results.layout.visibility = "hidden"

        super().__init__(
            progress_bar=self.progress_bar, children=[self.results], **kwargs
        )

    # TODO: This approach seems to be unreliable.
    # It might be better if to create a separate WizzardStep to display the final results
    def _display_results(self):
        if self.process_uuid is None:
            return
        process = load_node(self.process_uuid)
        if process.is_finished_ok:
            trajectory = process.outputs.relaxed_structures
            conformer_viewer = TrajectoryDataViewer(
                trajectory, configuration_tabs=["Selection", "Download"]
            )
            self.results.layout.visibility = "visible"
            with self.relaxed_structures:
                clear_output()
                display(conformer_viewer)
        else:
            with self.relaxed_structures:
                clear_output()
            self.results.layout.visibility = "hidden"

    def reset(self):
        super().reset()
        with self.relaxed_structures:
            clear_output()

    def _update_workflow_state(self):
        if self.process_uuid is None:
            self.workflow_status = None
            return

        process = load_node(self.process_uuid)
        process_state = process.process_state
        if process_state in (
            ProcessState.CREATED,
            ProcessState.RUNNING,
            ProcessState.WAITING,
        ):
            self.workflow_status = OptimizationWorkflowStatus.IN_PROGRESS
        elif (
            process_state in (ProcessState.EXCEPTED, ProcessState.KILLED)
            or process.is_failed
        ):
            self.workflow_status = OptimizationWorkflowStatus.FAILED
        elif process_state is ProcessState.FINISHED and process.is_finished_ok:
            self.workflow_status = OptimizationWorkflowStatus.FINISHED
