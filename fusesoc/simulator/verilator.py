import logging
import os
import shutil
import subprocess

from fusesoc.config import Config
from fusesoc import utils
from fusesoc.utils import pr_info
from fusesoc.core import OptionSectionMissing
from .simulator import Simulator

logger = logging.getLogger(__name__)

class Source(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)


class Verilator(Simulator):

    TOOL_NAME = 'VERILATOR'
    def __init__(self, system):
        super(Verilator, self).__init__(system)

        self.verilator_options = []
        self.src_files = []
        self.include_files = []
        self.include_dirs = []
        self.tb_toplevel = ""
        self.src_type = ''
        self.define_files = []
        self.libs = []
        self.top_module = ""

        if system.verilator is not None:
             self.verilator_options  = system.verilator.verilator_options
             self.src_files          = system.verilator.src_files
             self.include_files      = system.verilator.include_files
             self.tb_toplevel        = system.verilator.tb_toplevel
             self.src_type           = system.verilator.source_type
             self.define_files       = system.verilator.define_files
             self.top_module         = system.verilator.top_module

        self.sim_root = os.path.join(self.build_root, 'sim-verilator')
        if self.top_module == '':
            raise OptionSectionMissing('top_module')
        if self.tb_toplevel == '':
            raise OptionSectionMissing('tb_toplevel')


    def export(self):
        src_dir = self.system.files_root
        dst_dir = os.path.join(self.src_root, self.system.name)
        src_files = list(self.src_files)
        src_files += self.include_files
        src_files += [self.tb_toplevel]
        dirs = list(set(map(os.path.dirname, src_files)))
        for d in dirs:
            if not os.path.exists(os.path.join(dst_dir, d)):
                os.makedirs(os.path.join(dst_dir, d))

        for f in src_files:
            if(os.path.exists(os.path.join(src_dir, f))):
                shutil.copyfile(os.path.join(src_dir, f), 
                                os.path.join(dst_dir, f))

    def configure(self):
        super(Verilator, self).configure()
        self.export()
        self._write_config_files()
        #self.object_files = [os.path.splitext(os.path.basename(s))[0]+'.o' for s in self.src_files]

    def _write_config_files(self):
        self.verilator_file = 'input.vc'
        f = open(os.path.join(self.sim_root,self.verilator_file),'w')

        for include_dir in self.verilog.include_dirs:
            f.write("+incdir+" + os.path.abspath(include_dir) + '\n')
        for src_file in self.verilog.src_files:
            f.write(os.path.abspath(src_file) + '\n')
        f.close()
        #convert verilog defines into C file
        for files in self.define_files:
            read_file = os.path.join(self.src_root,files)
            write_file = os.path.join(os.path.dirname(os.path.join(self.sim_root,self.tb_toplevel)),os.path.splitext(os.path.basename(files))[0]+'.h')
            utils.convert_V2H(read_file, write_file)

    def _verilate(self):
        if self.src_type == 'systemC':
            args = ['--sc']
        else:
            args = ['--cc']
        args += ['-f', self.verilator_file]
        args += ['--top-module', self.top_module]
        args += ['--exe']
        args += ['-LDFLAGS "']
        args += ['-Wl,--start-group']
        args += [os.path.join(self.sim_root, s) for s in self.archives]
        args += ['-Wl,--end-group']
        args += [l for l in self.libs]
        args += ['"']
        args += ['-CFLAGS ' + '-I' + i for i in self.include_dirs]
        args += [os.path.join(self.src_root, self.system.name, self.tb_toplevel)]
        args += self.verilator_options

        cmd = utils.find_verilator()
        if cmd is None:
             raise RuntimeError("VERILATOR_ROOT not set and there is no verilator program in your PATH")
        cmd += ' ' + ' '.join(args)

        if (self.src_type == 'systemC') and not utils.check_systemc_env():
            raise RuntimeError("Need $SYSTEMC_LIBDIR and $SYSTEMC_INCLUDE in environment or when Verilator configured")

        l = utils.Launcher(cmd,
                           shell=True,
                           cwd = self.sim_root,
                           stderr = open(os.path.join(self.sim_root,'verilator.log'),'w'),
                           stdout = open(os.path.join(self.sim_root, 'verilator.out.log'),'w')
        )
        print('')
        pr_info("Starting Verilator:")
        if Config().verbose:
             pr_info("  Verilator working dir: " + self.sim_root)
             pr_info("  Verilator command: " + cmd)
        print('')
        l.run()

    def build(self):
        super(Verilator, self).build()
        self.archives = []
        for core_name in self.cores:
            core = self.cm.get_core(core_name)
            if core.verilator:
                 if core.verilator.archive:
                      self.archives += [core_name+'.a']
                 self.libs += core.verilator.libs
                 self.include_dirs += [os.path.join(self.src_root, core_name, d) for d in core.verilator.include_dirs]
        self.include_dirs += [os.path.dirname(os.path.join(self.sim_root, self.tb_toplevel))]

        self.include_dirs += [self.src_root]
        print('\n'.join(self.include_dirs))
        pr_info("Verilating source")
        self._verilate()
        for core_name in self.cores:
            core = self.cm.get_core(core_name)
            if core.verilator:
                 self._build(core, self.sim_root, self.src_root)

        pr_info("Building verilator executable:")
        args = ['-f', 'V' + self.top_module + '.mk', 'V' + self.top_module]
        l = utils.Launcher('make', args,
                       cwd=os.path.join(self.sim_root, 'obj_dir'),
                       stdout = open(os.path.join(self.sim_root,
                                                  'verilator.make.log'),'w'))
        if Config().verbose:
             pr_info("  Verilator executable working dir: "
                     + os.path.join(self.sim_root, 'obj_dir'))
             pr_info("  Verilator executable command: make " + ' '.join(args))
        l.run()

    def _build(self, core, sim_root, src_root):
        source_type = core.verilator.source_type
        if source_type == 'C' or source_type == '':
             self.build_C(core, sim_root, src_root)
        elif source_type == 'CPP':
            self.build_CPP(core, sim_root, src_root)
        elif source_type == 'systemC':
            self.build_SysC(core, sim_root, src_root)
        else:
            raise Source(core.verilator.source_type)

        if core.verilator._object_files:
            args = []
            args += ['rvs']
            args += [core.name+'.a']
            args += core.verilator._object_files
            l = utils.Launcher('ar', args,
                     cwd=sim_root)
            if Config().verbose:
                pr_info("  linker working dir: " + sim_root)
                pr_info("  linker command: ar " + ' '.join(args))
            l.run()
            print()

    def build_C(self, core, sim_root, src_root):
        args = ['-c']
        args += ['-std=c99']
        args += ['-I'+src_root]
        args += ['-I'+os.path.join(src_root, core.name, s) for s in core.verilator.include_dirs]
        for src_file in core.verilator.src_files:
            pr_info("Compiling " + src_file)
            l = utils.Launcher('gcc',
                     args + [os.path.join(src_root, core.name, src_file)],
                         cwd=sim_root,
                         stderr = open(os.path.join(sim_root, 'gcc.err.log'),'a'),
                         stdout = open(os.path.join(sim_root, 'gcc.out.log'),'a'))
            if Config().verbose:
                pr_info("  C compilation working dir: " + sim_root)
                pr_info("  C compilation command: gcc " + ' '.join(args) + ' ' + os.path.join(src_root, core, src_file))
            l.run()

    def build_CPP(self, core, sim_root, src_root):
        verilator_root = utils.get_verilator_root()
        if verilator_root is None:
            verilator_root = utils.get_verilator_root()
        args = ['-c']
        args += ['-I'+src_root]
        args += ['-I'+os.path.join(src_root, core.name, s) for s in self.include_dirs]
        args += ['-Iobj_dir']
        args += ['-I'+os.path.join(verilator_root,'include')]
        args += ['-I'+os.path.join(verilator_root,'include', 'vltstd')]
        for src_file in core.verilator.src_files:
            pr_info("Compiling " + src_file)
            l = utils.Launcher('g++', args + [os.path.join(src_root, core.name, src_file)],
                         cwd=sim_root,
                         stderr = open(os.path.join(sim_root, 'g++.err.log'),'a'))
            if Config().verbose:
                pr_info("  C++ compilation working dir: " + sim_root)
                pr_info("  C++ compilation command: g++ " + ' '.join(args) + ' ' + os.path.join(src_root, core.name, src_file))
            l.run()

    def build_SysC(self, core, sim_root, src_root):
        verilator_root = utils.get_verilator_root()
        args = ['-I.']
        args += ['-MMD']
        args += ['-I'+src_root]
        args += ['-I'+s for s in self.include_dirs]
        args += ['-Iobj_dir']
        args += ['-I'+os.path.join(verilator_root,'include')]
        args += ['-I'+os.path.join(verilator_root,'include', 'vltstd')]  
        args += ['-DVL_PRINTF=printf']
        args += ['-DVM_TRACE=1']
        args += ['-DVM_COVERAGE=0']
        if os.getenv('SYSTEMC_INCLUDE'):
            args += ['-I'+os.getenv('SYSTEMC_INCLUDE')]
        if os.getenv('SYSTEMC'):
            args += ['-I'+os.path.join(os.getenv('SYSTEMC'),'include')]
        args += ['-Wno-deprecated']
        if os.getenv('SYSTEMC_CXX_FLAGS'):
             args += [os.getenv('SYSTEMC_CXX_FLAGS')]
        args += ['-c']
        args += ['-g']

        for src_file in self.src_files:
            pr_info("Compiling " + src_file)
            l = Launcher('g++', args + [os.path.join(src_root, core.name, src_file)],
                         cwd=sim_root,
                         stderr = open(os.path.join(sim_root, 'g++.err.log'),'a'))
            if Config().verbose:
                pr_info("  SystemC compilation working dir: " + sim_root)
                pr_info("  SystemC compilation command: g++ " + ' '.join(args) + ' ' + os.path.join(src_root, core.name, src_file))
            l.run()
        
    def run(self, args):
        self.env = os.environ.copy()
        self.env['CORE_ROOT'] = os.path.abspath(self.system.core_root)
        self.env['BUILD_ROOT'] = os.path.abspath(self.build_root)
        self.env['SIM_ROOT'] = os.path.abspath(self.sim_root)
        #TODO: Handle arguments parsing
        pr_info("Running simulation")
        utils.Launcher('./V' + self.top_module,
                       args,
                       cwd=os.path.join(self.sim_root, 'obj_dir'),
                       env = self.env).run()
