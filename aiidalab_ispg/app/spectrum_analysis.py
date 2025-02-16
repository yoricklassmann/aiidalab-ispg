"""Tools for analyzing the spectra.

Authors:
    * Daniel Hollas <daniel.hollas@bristol.ac.uk>
    * Fay Abu-Al-Timen
    * Will Hobson
    * Konstantin Nomerotski
    * Kirstin Gerrand
    * Marco Barnfield
    * Emily Wright
"""

from enum import Enum, unique
from pathlib import Path

import bokeh.plotting as plt
from bokeh.models import Range1d, LogAxis, LogScale
import ipywidgets as ipw
import numpy as np
import traitlets as tl

from .utils import BokehFigureContext
from .widgets import HeaderWarning


@unique
class ActinicFlux(Enum):
    LOW = "Low flux"
    MEDIUM = "Medium flux"
    HIGH = "High flux"


class SpectrumAnalysisWidget(ipw.VBox):
    """A container class for organizing various analysis widgets"""

    conformer_transitions = tl.List(trait=tl.Dict, allow_none=True, default=None)

    cross_section_nm = tl.Dict(allow_none=True, default=None)

    disabled = tl.Bool(default=True)

    def __init__(self):
        title = ipw.HTML("<h3>Spectrum analysis</h3>")

        self.density_tab = DensityPlotWidget()
        ipw.dlink(
            (self, "conformer_transitions"),
            (self.density_tab, "conformer_transitions"),
        )
        ipw.dlink(
            (self, "disabled"),
            (self.density_tab, "disabled"),
        )

        self.photolysis_tab = PhotolysisPlotWidget()
        ipw.dlink(
            (self, "disabled"),
            (self.photolysis_tab, "disabled"),
        )
        ipw.dlink(
            (self, "cross_section_nm"),
            (self.photolysis_tab, "cross_section_nm"),
        )

        tab_components = [self.photolysis_tab, self.density_tab]
        tab = ipw.Tab(children=tab_components)
        tab.set_title(0, "Photolysis constant")
        tab.set_title(1, "Individual transitions")
        super().__init__(children=[title, tab])

    def reset(self):
        with self.hold_trait_notifications():
            self.disabled = True
            self.density_tab.reset()
            self.photolysis_tab.reset()


class DensityPlotWidget(ipw.VBox):
    """A widget for analyzing the correlation between excitation energies
    and oscillator strenghts.
    """

    conformer_transitions = tl.List(trait=tl.Dict, allow_none=True, default=None)
    disabled = tl.Bool(default=True)

    _BOKEH_LABEL = "energy-osc"

    def __init__(self):
        # https://docs.bokeh.org/en/latest/docs/user_guide/tools.html?highlight=tools#specifying-tools
        bokeh_tools = "save"
        figure_size = {
            "sizing_mode": "stretch_width",
            "height": 400,
            "max_width": 400,
        }
        self.figure = self._init_figure(tools=bokeh_tools, **figure_size)
        self.figure.layout = ipw.Layout(overflow="initial")

        super().__init__(children=[self.figure])

    def _init_figure(self, *args, **kwargs) -> BokehFigureContext:
        """Initialize Bokeh figure. Arguments are passed to bokeh.plt.figure()"""
        figure = BokehFigureContext(plt.figure(*args, **kwargs))
        f = figure.get_figure()
        f.xaxis.axis_label = "Excitation Energy (eV)"
        f.yaxis.axis_label = "Oscillator strength (-)"
        return figure

    @tl.observe("conformer_transitions")
    def _observe_conformer_transitions(self, change):
        self.disabled = True
        if change["new"] is None or len(change["new"]) == 0:
            self.reset()
            return
        self._update_density_plot()
        self.disabled = False

    def _update_density_plot(self):
        if self.conformer_transitions is None:
            return
        energies, osc_strengths = self._flatten_transitions()
        self.plot_scatter(energies, osc_strengths)

    def _flatten_transitions(self) -> tuple:
        # Flatten transitions for all conformers.
        # In the future, we might want to plot individual conformers
        # separately in the scatter plot.
        energies = np.array(
            [
                transitions["energy"]
                for conformer in self.conformer_transitions
                for transitions in conformer["transitions"]
            ]
        )
        osc_strengths = np.array(
            [
                transitions["osc_strength"]
                for conformer in self.conformer_transitions
                for transitions in conformer["transitions"]
            ]
        )
        return energies, osc_strengths

    def plot_scatter(self, energies: np.ndarray, osc_strengths: np.ndarray):
        """Update existing scatter plot or create a new one."""
        self.figure.remove_renderer(self._BOKEH_LABEL, update=True)
        f = self.figure.get_figure()
        f.x_range.range_padding = f.y_range.range_padding = 0.1
        f.circle(
            energies, osc_strengths, name=self._BOKEH_LABEL, fill_color="black", size=5
        )
        self.figure.update()

    def reset(self):
        with self.hold_trait_notifications():
            self.disabled = True
            self.figure.clean()

    @tl.observe("disabled")
    def _observe_disabled(self, _: dict):
        pass


class PhotolysisPlotWidget(ipw.VBox):
    """A widget for calculating and plotting photolysis rate constant.

    Differential photolysis rate of the molecule is calculated and plotted.
    The intensity of actinic flux can be selected by the user - either High,
    Medium, or Low. The quantum yield can be altered by the user.
    The total integrated photolysis rate constant is calculated as well.
    """

    disabled = tl.Bool(default=True)

    cross_section_nm = tl.Dict(allow_none=True, default=None)

    def __init__(self):
        self.header_warning = HeaderWarning(dismissible=False)
        self.header_warning.layout.width = "500px"

        self.flux_toggle = ipw.ToggleButtons(
            options=[(flux.value, flux) for flux in ActinicFlux],
            value=ActinicFlux.HIGH,
        )

        self.flux_toggle.observe(self._observe_flux_toggle, names="value")

        self.yield_slider = ipw.FloatSlider(
            min=0.01,
            max=1,
            step=0.01,
            value=1,
            description="Quantum yield",
            continuous_update=True,
            disabled=False,
            style={"description_width": "initial"},
        )
        self.yield_slider.observe(self.handle_slider_change, names="value")

        self.autoscale_yaxis = ipw.Checkbox(
            value=True,
            description="Autoscale y-axis",
            indent=False,
        )

        self.flux_data = self.read_actinic_fluxes()

        self.total_rate = ipw.HTML(
            description="Photolysis rate constant (s$^{-1}$) =",
            style={"description_width": "initial"},
        )

        bokeh_tools = "pan,wheel_zoom,box_zoom,reset,save"
        figure_size = {
            "sizing_mode": "stretch_width",
            "height": 400,
            "max_width": 500,
        }
        self.figure = self._init_figure(tools=bokeh_tools, **figure_size)
        self.figure.layout = ipw.Layout(overflow="initial")

        self.controls = ipw.VBox(
            children=[
                self.header_warning,
                self.flux_toggle,
                self.yield_slider,
                self.autoscale_yaxis,
            ]
        )

        super().__init__(
            children=[
                self.controls,
                self.total_rate,
                self.figure,
            ]
        )

    def _init_figure(self, *args, **kwargs) -> BokehFigureContext:
        """Initialize Bokeh figure. Arguments are passed to bokeh.plt.figure()"""
        figure = BokehFigureContext(plt.figure(*args, **kwargs))
        f = figure.get_figure()
        f.xaxis.axis_label = r"$$λ \text{(nm)}$$"
        f.yaxis.axis_label = r"$$j (\text{s}^{-1} \text{nm}^{-1})$$"
        f.x_range = Range1d(280, 749)
        f.y_range = Range1d(0, 3.5e-05)

        f.extra_y_ranges = {"V": Range1d(start=1.0, end=1e15)}
        f.extra_y_scales = {"V": LogScale()}
        f.add_layout(
            LogAxis(
                y_range_name="V",
                axis_label=r"$$F \text{(quanta cm}^{-2} \text{s}^{-1}  \text{nm}^{-1}\text{)}$$",
            ),
            "right",
        )

        return figure

    @tl.observe("cross_section_nm")
    def _observe_cross_section_nm(self, change: dict):
        """Observe changes to the spectrum data and update the J plot accordingly.
        Check that fluxdata overlaps with the spectrum data.
        """
        if change["new"] is None or len(change["new"]) == 0:
            self.reset()
            return

        flux_min = min(self.flux_data["wavelengths"])
        flux_max = max(self.flux_data["wavelengths"])
        spectrum_max = max(self.cross_section_nm["wavelengths"])
        spectrum_min = min(self.cross_section_nm["wavelengths"])

        # Check whether spectrum data overlap with flux data
        if spectrum_max <= flux_min or spectrum_min >= flux_max:
            self.reset()
            self.header_warning.show("Spectrum outside of actinic range.")
            return

        self.header_warning.hide()
        self._update_j_plot(
            flux_type=self.flux_toggle.value, quantumY=self.yield_slider.value
        )
        self.disabled = False

    def _observe_flux_toggle(self, change: dict):
        """Redraw spectra when user changes flux via toggle"""
        self._update_j_plot(flux_type=change["new"], quantumY=self.yield_slider.value)

    def handle_slider_change(self, change: dict):
        """Redraw spectra when user changes quantum yield via slider"""
        self._update_j_plot(flux_type=self.flux_toggle.value, quantumY=change["new"])

    def _update_j_plot(self, flux_type: ActinicFlux, quantumY: float):
        """
        Update the J plot based on the given flux type and quantum yield

        :param flux_type: Which of the predefined actinic fluxes should be used.
        :param quantumY: The quantum yield value to use in the calculation.

        :return: A tuple containing the J values and wavelengths used in the plot.
        """

        if self.cross_section_nm is None:
            self.total_rate.value = ""
            return

        wavelengths, j_diff = self.calculate_j_diff(
            self.cross_section_nm, flux_type, quantum_yield=quantumY
        )
        # Integrate the differential j plot to get the total rate.
        # Use trapezoid rule.
        j_total = np.trapz(j_diff, x=wavelengths)
        self.total_rate.value = f"<b>{np.format_float_scientific(j_total, 3)}</b>"

        # Plot slightly smoothed j_diff to make it less rugged.
        # Our theoretical spectra do not have 1nm resolution anyway.
        j_smoothed = self.smooth_j_diff(j_diff)

        self.plot_photolysis_rate(wavelengths, j_smoothed, update=False)
        self.plot_flux(flux_type, update=True)

    def reset(self):
        """
        Reset the figure and its associated widgets to their default values.
        """
        with self.hold_trait_notifications():
            self.disabled = True
            self.figure.clean()
            self.flux_toggle.value = ActinicFlux.HIGH
            self.yield_slider.value = 1
            self.total_rate.value = ""
            self.autoscale_yaxis.value = True
            self.header_warning.hide()

    @tl.observe("disabled")
    def _observe_disabled(self, change: dict):
        disabled = change["new"]
        with self.hold_trait_notifications():
            for child in self.controls.children:
                child.disabled = disabled

    def read_actinic_fluxes(self) -> dict:
        """Read in actinic flux data from a CSV file.

        :return: A tuple containing the wavelength and low, medium, and high actinic flux data.
        """
        wavelengths, low_flux, medium_flux, high_flux = np.loadtxt(
            fname=Path(__file__).parent / "static" / "StandardActinicFluxes2.csv",
            delimiter=",",
            skiprows=1,
            unpack=True,
            usecols=(2, 3, 4, 5),
        )
        return {
            "wavelengths": wavelengths,
            ActinicFlux.LOW: low_flux,
            ActinicFlux.MEDIUM: medium_flux,
            ActinicFlux.HIGH: high_flux,
        }

    @staticmethod
    def smooth_j_diff(j_diff: np.ndarray) -> np.ndarray:
        kernel_size = 3
        kernel = np.ones(kernel_size) / kernel_size
        return np.convolve(j_diff, kernel, mode="same")

    def calculate_j_diff(
        self, cross_section_nm: dict, flux_type: ActinicFlux, quantum_yield: float
    ):
        """
        Calculate the J values for the given level and quantum yield.
        Smooth the curve using np.convolve(x, kernel = 3, mode = "valid")

        :param flux_type: The type of actinic flux to use in the calculation.
        :param quantum_yield: The quantum yield value to use in the calculation.
        :return: np.ndarray of smoothed J values.
        """
        wavelengths = self.flux_data["wavelengths"]
        cross_section_interp = self.interpolate_cross_section(
            wavelengths, cross_section_nm
        )
        j_diff = cross_section_interp * self.flux_data[flux_type] * quantum_yield
        return wavelengths, j_diff

    def interpolate_cross_section(
        self, flux_wavelengths: np.ndarray, cross_section_nm: dict
    ) -> np.ndarray:
        """
        Prepare the molecular intensity data for plotting by interpolating cross section onto actinic flux x values.

        :param flux_wavelengths: wavelengths corresponding to flux data
        :param cross_section_nm: theoretical cross section data, packed in dict
        :return: The interpolated cross section data.
        """
        wavelengths = cross_section_nm["wavelengths"]
        cross_section = cross_section_nm["cross_section"]
        return np.interp(
            flux_wavelengths,
            wavelengths,
            cross_section,
            left=0.0,
            right=0.0,
        )

    def plot_line(self, x: np.ndarray, y: np.ndarray, label: str, update=True, **args):
        """Plot a line on the figure with the given x and y data and label.

        :param x: The x data for the line.
        :param y: The y data for the line.
        :param label: The label for the line.
        :param update: Whether to update the figure after plotting the line.
        :param args: Additional arguments to pass to the line plot function.
        """
        self.remove_line(label, update=update)

        f = self.figure.get_figure()
        f.line(x, y, name=label, **args)
        if update:
            self.figure.update()

    def plot_photolysis_rate(
        self, wavelengths: np.ndarray, j_diff: np.ndarray, update=True
    ):
        self.plot_line(wavelengths, j_diff, label="rate", update=update, line_width=2)
        y_range_max = 1.2 * j_diff.max()
        self.update_y_axis(y_range_max, update=update)

    def update_y_axis(self, end: float, update=True):
        """Update the y-axis range of the figure.

        :param end: The new end value for the y-axis range.
        """
        if not self.autoscale_yaxis.value:
            return
        f = self.figure.get_figure()
        f.y_range.start = 0
        f.y_range.end = end
        if update:
            self.figure.update()

    def plot_flux(self, flux_type: ActinicFlux, update=True, **args):
        """
        Plot flux data in logarithmic axis.

        :param level: The level of the flux data to be plotted.
        :param update: Whether to update the figure after adding the line. Default is True.
        :param args: Additional arguments to be passed to the line function.
        """
        x = self.flux_data["wavelengths"]
        y = self.flux_data[flux_type]
        self.plot_line(
            x, y, label="log_flux", update=update, y_range_name="V", color="red", **args
        )

    def remove_line(self, label: str, update=True):
        """
        Remove a line from the figure.

        :param label: The name of the line to be removed.
        :param update: Whether to update the figure after removing the line. Default is True.
        """
        self.figure.remove_renderer(label, update=update)
