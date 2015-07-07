# Stommel gyre test case in 3D
# ============================
#
# Wind-driven geostrophic gyre in larege basin.
# Setup is according to [1]. This version us for 3D equations. As the problem
# is purely baroclinic the solution is the same as in 2D.
#
# [1] Comblen, R., Lambrechts, J., Remacle, J.-F., and Legat, V. (2010).
#     Practical evaluation of five partly discontinuous finite element pairs
#     for the non-conservative shallow water equations. International Journal
#     for Numerical Methods in Fluids, 63(6):701-724.
#
# Tuomas Karna 2015-04-28

from cofs import *

mesh2d = Mesh('stommel_square.msh')
outputDir = createDirectory('outputs')
printInfo('Loaded mesh '+mesh2d.name)
printInfo('Exporting to '+outputDir)
depth = 1000.0
layers = 6
T = 75*12*2*3600.
TExport = 3600.*2

# bathymetry
P1_2d = FunctionSpace(mesh2d, 'CG', 1)
P1v_2d = VectorFunctionSpace(mesh2d, 'CG', 1)
bathymetry2d = Function(P1_2d, name='Bathymetry')
bathymetry2d.assign(depth)

# Coriolis forcing
coriolis2d = Function(P1_2d)
f0, beta = 1.0e-4, 2.0e-11
coriolis2d.interpolate(
    Expression('f0+beta*(x[1]-y_0)', f0=f0, beta=beta, y_0=0.0)
    )

# Wind stress
windStress2d = Function(P1v_2d, name='wind stress')
tau_max = 0.1
L_y = 1.0e6
windStress2d.interpolate(Expression(('tau_max*sin(pi*x[1]/L)', '0'), tau_max=tau_max, L=L_y))

# linear dissipation: tau_bot/(h*rho) = -bf_gamma*u
lin_drag = Constant(1e-6)

# --- create solver ---
solverObj = solver.flowSolver(mesh2d, bathymetry2d, layers)
solverObj.cfl_2d = 1.0
solverObj.nonlin = False
solverObj.solveSalt = False
solverObj.solveVertDiffusion = False
solverObj.useBottomFriction = False
solverObj.useALEMovingMesh = False
#solverObj.useModeSplit = False
solverObj.baroclinic = False
solverObj.coriolis = coriolis2d
solverObj.wind_stress = windStress2d
solverObj.lin_drag = lin_drag
solverObj.TExport = TExport
solverObj.T = T
solverObj.dt_2d = 20.0
solverObj.dt = 450.0
solverObj.outputDir = outputDir
solverObj.uAdvection = Constant(0.01)
solverObj.checkVolConservation2d = True
solverObj.checkVolConservation3d = True
solverObj.fieldsToExport = ['uv2d', 'elev2d', 'uv3d',
                            'w3d', 'uv2d_dav']
solverObj.timerLabels = []

solverObj.mightyCreator()
solverObj.assignInitialConditions()

solverObj.iterate()
