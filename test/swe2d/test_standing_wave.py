# Test for temporal convergence of cranknicolson and pressureprojection picard timesteppers,
# tests convergence of a single period of a standing wave in a rectangular channel.
# This only tests against a linear solution, so does not really test whether the splitting
# in pressureprojectionpicard between nonlinear momentum and linearized wave equation terms is correct.
# pressureprojectionpicard does need two iterations to ensure 2nd order convergence
from thetis import *
import pytest
import math


@pytest.mark.parametrize("timesteps,max_rel_err", [
    (10, 0.02), (20, 5e-3)])
# with nonlin=True and nx=100 this converges for the series
#  (10,0.02), (20,5e-3), (40, 1.25e-3)
# with nonlin=False further converge is possible
@pytest.mark.parametrize("timestepper", [
    'cranknicolson', 'pressureprojectionpicard', ])
def test_steady_state_channel(timesteps, max_rel_err, timestepper, do_export=False):

    lx = 5e3
    ly = 1e3
    nx = 50
    mesh2d = RectangleMesh(nx, 1, lx, ly)

    n = timesteps
    depth = 100.
    g = physical_constants['g_grav'].dat.data[0]
    c = math.sqrt(g*depth)
    period = 2*lx/c
    dt = period/n
    t_end = period-0.1*dt  # make sure we don't overshoot

    x = SpatialCoordinate(mesh2d)
    elev_init = cos(pi*x[0]/lx)

    # bathymetry
    p1_2d = FunctionSpace(mesh2d, 'CG', 1)
    bathymetry_2d = Function(p1_2d, name="bathymetry")
    bathymetry_2d.assign(depth)

    # --- create solver ---
    solver_obj = solver2d.FlowSolver2d(mesh2d, bathymetry_2d)
    solver_obj.options.use_nonlinear_equations = True
    solver_obj.options.t_export = dt
    solver_obj.options.t_end = t_end
    solver_obj.options.no_exports = not do_export
    solver_obj.options.element_family = 'dg-dg'
    solver_obj.options.timestepper_type = timestepper
    solver_obj.options.shallow_water_theta = 0.5
    if timestepper == 'cranknicolson':
        solver_obj.options.solver_parameters_sw = {
            'ksp_type': 'preonly',
            'pc_type': 'lu',
            'pc_factor_mat_solver_package': 'mumps',
            'snes_monitor': False,
            'snes_type': 'newtonls',
        }
    elif timestepper == 'pressureprojectionpicard':
        # solver options for the linearized wave equation terms
        solver_obj.options.solver_parameters_sw = {
            'snes_type': 'ksponly',  # we've linearized, so no snes needed
            'ksp_type': 'preonly',  # we solve the full schur complement exactly, so no need for outer krylov
            'pc_type': 'fieldsplit',
            'pc_fieldsplit_type': 'schur',
            'pc_fieldsplit_schur_fact_type': 'full',
            'pc_fieldsplit_schur_precondition': 'selfp',
            # velocity mass block:
            'fieldsplit_0_ksp_type': 'preonly',  # NOTE: this is only an exact solver for the velocity mass block if velocity is DG
            'fieldsplit_0_pc_type': 'ilu',
            'fieldsplit_1_ksp_type': 'gmres',
            # schur complement:
            'fieldsplit_1_pc_type': 'gamg',
            'fieldsplit_1_ksp_max_it': 100,
            'fieldsplit_1_ksp_converged_reason': True,
        }
        options.solver_parameters_sw_momentum = {
            'snes_monitor': True,
            'ksp_type': 'gmres',
            'ksp_converged_reason': True,
            'pc_type': 'bjacobi',
            'pc_bjacobi_type': 'ilu',
        }
    solver_obj.options.dt = dt

    # boundary conditions
    solver_obj.bnd_functions['shallow_water'] = {}
    parameters['quadrature_degree'] = 5

    solver_obj.create_equations()
    solver_obj.assign_initial_conditions(elev=elev_init)

    solver_obj.iterate()

    uv, eta = solver_obj.fields.solution_2d.split()

    area = lx*ly
    rel_err = errornorm(elev_init, eta)/math.sqrt(area)
    print_output(rel_err)
    assert(rel_err < max_rel_err)
    print_output("PASSED")


if __name__ == '__main__':
    test_steady_state_channel(do_export=True)
