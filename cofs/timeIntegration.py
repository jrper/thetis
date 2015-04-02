"""
Time integration schemes for 2D, 3D, and coupled 2D-3D equations.

Tuomas Karna 2015-03-27
"""
from utility import *


def cosTimeAvFilter(M):
    """
    Raised cos time average filters as in older versions of ROMS.
    a_i : weights for t_{n+1}
          sum(a_i) = 1.0, sum(i*a_i/M) = 1.0
    b_i : weights for t_{n+1/2}
          sum(b_i) = 1.0, sum(i*b_i/M) = 0.5

    Filters have lenght 2*M.
    """
    l = np.arange(1, 2*M+1, dtype=float)/M
    # a raised cos centered at M
    a = np.zeros_like(l)
    ix = (l >= 0.5) * (l <= 1.5)
    a[ix] = 1 + np.cos(2*np.pi*(l[ix]-1))
    a /= sum(a)

    # b as in Shchepetkin and MacWilliams 2005
    b = np.cumsum(a[::-1])[::-1]/M
    # correct b to match 2nd criterion exactly
    error = sum(l*b)-0.5
    p = np.linspace(-1,1,len(b))
    p /= sum(l*p)
    b -= p*error

    ## weird cos filter
    ## TODO check with waveEq if this is any better than uncorrected b above
    #b = np.zeros_like(l)
    #alpha = 0.40

    ##maxiter = 100
    ##tol = 1e-8
    ##ix = (l <= 1.0 + alpha)
    ##for i in range(maxiter):
        ##b[:] = 0
        ##ix = (l <= 1.0 + alpha)
        ##b[ix] = np.cos(np.pi*(l[ix]-alpha)) + 1
        ##b /= sum(b)
        ##err = sum(l*b) - 0.5
        ##print 'alpha', alpha, err
        ##if abs(err) < tol :
            ##break
        ##alpha -= err

    #gtol = 1e-10
    #from scipy.optimize import fmin_bfgs as minimize
    #def costfun(alpha, b, l):
        #b[:] = 0
        #ix = (l <= 1.0 + alpha)
        #b[ix] = np.cos(np.pi*(l[ix]-alpha)) + 1
        #b /= sum(b)
        #return (sum(l*b) - 0.5)**2
    #res = minimize(costfun, 0.4, args=(b, l), gtol=gtol)

    M_star = np.nonzero((np.abs(a) > 1e-10) + (np.abs(b) > 1e-10))[0].max()
    if commrank==0:
      print 'M', M, M_star
      print 'a', sum(a), sum(l*a)
      print 'b', sum(b), sum(l*b)

    return M_star, [float(f) for f in a], [float(f) for f in b]


class macroTimeStepIntegrator(object):
    """Takes an explicit time integrator and iterates it over M time steps.
    Computes time averages to represent solution at M*dt resolution."""
    # NOTE the time averages can be very diffusive
    # NOTE diffusivity depends on M and the choise of time av filter
    # NOTE boxcar filter is very diffusive!
    def __init__(self, timeStepperCls, M, restartFromAv=False):
        self.timeStepper = timeStepperCls
        self.M = M
        self.restartFromAv = restartFromAv
        # functions to hold time averaged solutions
        space = self.timeStepper.solution_old.function_space()
        self.solution_n = Function(space)
        self.solution_nplushalf = Function(space)
        self.solution_start = Function(space)
        self.M_star, self.w_full, self.w_half = cosTimeAvFilter(M)

    def initialize(self, solution):
        self.timeStepper.initialize(solution)
        self.solution_n.assign(solution)
        self.solution_nplushalf.assign(solution)
        self.solution_start.assign(solution)

    def advance(self, t, dt, solution, updateForcings, verbose=False):
        """Advances equations for one macro time step DT=M*dt"""
        M = self.M
        solution_old = self.timeStepper.solution_old
        if self.restartFromAv:
            # initialize from time averages
            solution_old.assign(self.solution_n)
            solution.assign(self.solution_n)
        else:
            # start from saved istantaneous state
            solution_old.assign(self.solution_start)
            solution.assign(self.solution_start)
        # reset time filtered solutions
        # filtered to T_{n+1/2}
        self.solution_nplushalf.assign(0.0)
        # filtered to T_{n+1}
        self.solution_n.assign(0.0)

        # advance fields from T_{n} to T{n+1}
        if verbose and commrank == 0:
            sys.stdout.write('Solving 2D ')
        for i in range(self.M_star):
            self.timeStepper.advance(t + i*dt, dt, solution, updateForcings)
            self.solution_nplushalf += self.w_half[i]*solution
            self.solution_n += self.w_full[i]*solution
            if verbose and commrank == 0:
                sys.stdout.write('.')
                if i == M-1:
                    sys.stdout.write('|')
                sys.stdout.flush()
            if i == M-1:
                # store state at T_{n+1}
                self.solution_start.assign(solution)
        if verbose and commrank == 0:
            sys.stdout.write('\n')
            sys.stdout.flush()
        # use filtered solution as output
        solution.assign(self.solution_n)


class timeIntegrator(object):
    """Base class for all time integrator objects."""
    # TODO move to timeIntegrator.py
    def __init__(self, equation):
        self.equation = equation

    def advance(self):
        raise NotImplementedError(('This method must be implemented '
                                   'in the derived class'))


class SSPRK33(timeIntegrator):
    """
    3rd order Strong Stability Preserving Runge-Kutta scheme, SSP(3,3).

    This scheme has Butcher tableau
    0   |
    1   | 1
    1/2 | 1/4 1/4
    ---------------
        | 1/6 1/6 2/3

    CFL coefficient is 1.0
    """
    def __init__(self, equation, dt, solver_parameters=None,
                 funcs_nplushalf={}):
        """Creates forms for the time integrator"""
        timeIntegrator.__init__(self, equation)
        self.explicit = True
        self.CFL_coeff = 1.0
        self.solver_parameters = solver_parameters

        massTerm = self.equation.massTerm
        RHS = self.equation.RHS
        Source = self.equation.Source

        self.solution_old = Function(self.equation.space)

        self.K0 = Function(self.equation.space)
        self.K1 = Function(self.equation.space)
        self.K2 = Function(self.equation.space)

        # dict of all input functions needed for the equation
        self.funcs = self.equation.kwargs
        # create functions to hold the values of previous time step
        self.funcs_old = {}
        for k in self.funcs:
            if self.funcs[k] is not None:
                self.funcs_old[k] = Function(self.funcs[k].function_space())
        self.funcs_nplushalf = funcs_nplushalf
        # values used in equations
        self.args = {}
        for k in self.funcs_old:
            self.args[k] = Function(self.funcs[k].function_space())

        u_old = self.solution_old
        u_tri = self.equation.tri

        dt_const = Constant(dt)
        a_RK = massTerm(u_tri)
        L_RK = dt_const*(RHS(u_old, **self.args) + Source(**self.args))

        probK0 = LinearVariationalProblem(a_RK, L_RK, self.K0)
        self.solverK0 = LinearVariationalSolver(probK0,
                                                solver_parameters=self.solver_parameters)
        probK1 = LinearVariationalProblem(a_RK, L_RK, self.K1)
        self.solverK1 = LinearVariationalSolver(probK1,
                                                solver_parameters=self.solver_parameters)
        probK2 = LinearVariationalProblem(a_RK, L_RK, self.K2)
        self.solverK2 = LinearVariationalSolver(probK2,
                                                solver_parameters=self.solver_parameters)

    def initialize(self, solution):
        """Assigns initial conditions to all required fields."""
        self.solution_old.assign(solution)
        # assing values to old functions
        for k in self.funcs_old:
            self.funcs_old[k].assign(self.funcs[k])

    def advance(self, t, dt, solution, updateForcings):
        """Advances equations for one time step."""

        # stage 0
        for k in self.args:  # set args to t
            self.args[k].assign(self.funcs_old[k])
        if updateForcings is not None:
            updateForcings(t)
        self.solverK0.solve()
        # stage 1
        self.solution_old.assign(solution + self.K0)
        for k in self.args:  # set args to t+dt
            self.args[k].assign(self.funcs[k])
        if updateForcings is not None:
            updateForcings(t+dt)
        self.solverK1.solve()
        # stage 2
        self.solution_old.assign(solution + 0.25*self.K0 + 0.25*self.K1)
        for k in self.args:  # set args to t+dt/2
            if k in self.funcs_nplushalf:
                self.args[k].assign(self.funcs_nplushalf[k])
            else:
                self.args[k].assign(0.5*self.funcs[k] + 0.5*self.funcs_old[k])
        if updateForcings is not None:
            updateForcings(t+dt/2)
        self.solverK2.solve()
        # final solution
        solution.assign(solution + (1.0/6.0)*self.K0 + (1.0/6.0)*self.K1 +
                        (2.0/3.0)*self.K2)

        # store old values
        for k in self.funcs_old:
            self.funcs_old[k].assign(self.funcs[k])
        self.solution_old.assign(solution)

    def solveStage(iStage, solution, sol_stage):
        if iStage == 0:
            # stage 0
            self.solution_old.assign(solution)
            for k in self.args:  # set args to t
                self.args[k].assign(self.funcs_old[k])
            if updateForcings is not None:
                updateForcings(t)
            self.solverK0.solve()
            sol_stage.assign(solution + self.K0)
        elif iStage == 1:
            # stage 1
            self.solution_old.assign(sol_stage)
            for k in self.args:  # set args to t+dt
                self.args[k].assign(self.funcs[k])
            if updateForcings is not None:
                updateForcings(t+dt)
            self.solverK1.solve()
            sol_stage.assign(solution + 0.25*self.K0 + 0.25*self.K1)
        elif iStage == 2:
            # stage 2
            self.solution_old.assign(sol_stage)
            for k in self.args:  # set args to t+dt/2
                if k in self.funcs_nplushalf:
                    self.args[k].assign(self.funcs_nplushalf[k])
                else:
                    self.args[k].assign(0.5*self.funcs[k] + 0.5*self.funcs_old[k])
            if updateForcings is not None:
                updateForcings(t+dt/2)
            self.solverK2.solve()
            # final solution
            solution.assign(solution + (1.0/6.0)*self.K0 + (1.0/6.0)*self.K1 +
                            (2.0/3.0)*self.K2)
            #sol_stage.assign(solution)


class CrankNicolson(timeIntegrator):
    """Standard Crank-Nicolson time integration scheme."""
    def __init__(self, equation, dt, gamma=0.6):
        """Creates forms for the time integrator"""
        timeIntegrator.__init__(self, equation)

        massTerm = self.equation.massTerm
        RHS = self.equation.RHS
        Source = self.equation.Source

        invdt = Constant(1.0/dt)

        self.solution_old = Function(self.equation.space)

        # dict of all input functions needed for the equation
        self.funcs = self.equation.kwargs
        # create functions to hold the values of previous time step
        self.funcs_old = {}
        for k in self.funcs:
            if self.funcs[k] is not None:
                self.funcs_old[k] = Function(self.funcs[k].function_space())

        u = self.equation.solution
        u_old = self.solution_old
        u_tri = self.equation.tri
        #Crank-Nicolson
        gamma_const = Constant(gamma)
        self.F = (invdt*massTerm(u) - invdt*massTerm(u_old) -
                  gamma_const*RHS(u, **self.funcs) -
                  gamma_const*Source(**self.funcs) -
                  (1-gamma_const)*RHS(u_old, **self.funcs_old) -
                  (1-gamma_const)*Source(**self.funcs_old))

        self.A = (invdt*massTerm(u_tri) -
                  gamma_const*RHS(u_tri, **self.funcs))
        self.L = (invdt*massTerm(u_old) + gamma_const*Source(**self.funcs) +
                  (1-gamma_const)*RHS(u_old, **self.funcs_old) +
                  (1-gamma_const)*Source(**self.funcs_old))

    def initialize(self, solution):
        """Assigns initial conditions to all required fields."""
        self.solution_old.assign(solution)
        # assing values to old functions
        for k in self.funcs_old:
            self.funcs_old[k].assign(self.funcs[k])

    def advance(self, t, dt, solution, updateForcings):
        """Advances equations for one time step."""
        solver_parameters = {
            'snes_type': 'newtonls',
            'snes_monitor': True,
        }
        if updateForcings is not None:
            updateForcings(t+dt)
        self.solution_old.assign(solution)
        solve(self.F == 0, solution, solver_parameters=solver_parameters)
        # shift time
        for k in self.funcs_old:
            self.funcs_old[k].assign(self.funcs[k])

    def advanceLinear(self, t, dt, solution, updateForcings):
        """Advances equations for one time step."""
        solver_parameters = {
            'snes_type': 'ksponly',
        }
        if updateForcings is not None:
            updateForcings(t+dt)
        self.solution_old.assign(solution)
        solve(self.A == self.L, solution, solver_parameters=solver_parameters)
        # shift time
        for k in self.funcs_old:
            self.funcs_old[k].assign(self.funcs[k])