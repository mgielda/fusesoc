import os
from fusesoc.simulator.simulator import Simulator
import logging
from fusesoc.utils import Launcher, pr_err

logger = logging.getLogger(__name__)

class Xsim(Simulator):

    TOOL_NAME = 'XSIM'
    def __init__(self, system):

        self.cores = []
        self.xsim_options = []

        if system.xsim is not None:
            self.xsim_options = system.xsim.xsim_options
        super(Xsim, self).__init__(system)
        self.sim_root = os.path.join(self.build_root, 'sim-xsim')




    def configure(self):
        super(Xsim, self).configure()
        self._write_config_files()

    def _write_config_files(self):
        xsim_file = 'xsim.prj'
        f1 = open(os.path.join(self.sim_root,xsim_file),'w')
        for src_file in self.verilog.src_files:
            f1.write('verilog work ' + os.path.relpath(src_file, self.sim_root) + '\n')
        for src_file in self.verilog.tb_src_files:
            f1.write('verilog work ' + os.path.relpath(src_file, self.sim_root) + '\n')
        f1.close()

        tcl_file = 'xsim.tcl'
        f2 = open(os.path.join(self.sim_root,tcl_file),'w')
        f2.write('add_wave -radix hex /\n')
        f2.write('run all\n')
        f2.close()

    def build(self):
        super(Xsim, self).build()

        #Check if any VPI modules are present and display warning
        if len(self.vpi_modules) > 0:
            modules = [m['name'] for m in self.vpi_modules]
            pr_err('VPI modules not supported by Xsim: %s' % ', '.join(modules))

        #Build simulation model
        args = []
        args += [ self.toplevel]
        args += ['--prj', 'xsim.prj']      # list of design files
        args += ['--timescale', '1ps/1ps'] # default timescale to prevent error if unspecified
        args += ['--snapshot', 'fusesoc']  # name of the design to simulate
        args += ['--debug', 'typical']     # capture waveforms

        for include_dir in self.verilog.include_dirs:
            args += ['-i', os.path.relpath(include_dir, self.sim_root)]
        for include_dir in self.verilog.tb_include_dirs:
            args += ['-i', os.path.relpath(include_dir, self.sim_root)]

        args += self.xsim_options

        Launcher('xelab', args,
                 cwd      = self.sim_root,
                 errormsg = "Failed to compile Xsim simulation model").run()

    def run(self, args):
        super(Xsim, self).run(args)

        #FIXME: Handle failures. Save stdout/stderr.
        args = []
        args += ['--gui']                                 # Interactive
        args += ['--tclbatch', 'xsim.tcl']                 # Simulation commands
        args += ['--log', 'xsim.log']                      # Log file
        args += ['--wdb', 'xsim.wdb']                      # Simulation waveforms database
        args += ['fusesoc']                                # Snapshot name
        #args += ['+'+s for s in self.plusargs]             # Plusargs
        Launcher('xsim', args,
                 cwd = self.sim_root,
                 errormsg = "Failed to run Xsim simulation").run()

        super(Xsim, self).done(args)
