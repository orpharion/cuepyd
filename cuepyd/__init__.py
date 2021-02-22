import subprocess as _sp
import dataclasses as _d
import typing as _t
import itertools as _it
import enum as _e
import pathlib as _pl
import signal as _s

_A = _t.TypeVar('_A')


@_d.dataclass
class CalledProcessError(_sp.SubprocessError):
    proc: _d.InitVar[_sp.CompletedProcess]
    input: bytes = b''
    args: list[str] = _d.field(init=False)
    return_code: int = _d.field(init=False)
    output: bytes = _d.field(init=False)
    error: bytes = _d.field(init=False)

    def __post_init__(self, proc):
        self.args = proc.args
        self.return_code = proc.returncode
        self.output = proc.stdout
        self.error = proc.stderr

    def __str__(self):
        if not self.return_code:
            raise ValueError('Invalid return code 0 for subprocess.')
        if self.return_code < 0:
            try:
                return_context = f'died with {_s.Signals(-self.return_code)}.'
            except ValueError:
                return_context = f'died with unknown signal {-self.return_code:d}.'
        else:
            return_context = f'returned non-zero exit status {self.return_code:d}.'
        return (f'Subprocess {" ".join(self.args)} {return_context}' +
                ('' if not self.input else f'\n\tinput:\t{self.input.decode()}') +
                ('' if not self.error else f'\n\terror:\t{self.error.decode()}') +
                ('' if not self.output else f'\n\toutput:\t{self.output.decode()}'))

    @staticmethod
    def check(proc: _sp.CompletedProcess, input: bytes=b''):
        if proc.returncode != 0:
            e = CalledProcessError(proc, input)
            print(e)
            raise CalledProcessError(proc, input)


def _field_type(field: _d.Field):
    if getattr(field.type, '__origin__', None) == _t.Union:
        if field.type.__args__[1] is None:
            return field.type.__args__[0]
        else:
            raise NotImplementedError
    return field.type


def _field_name_flag(field: _d.Field):
    """
    | python      | flag          | Comment                                                            |
    |-------------|---------------|--------------------------------------------------------------------|
    | identifier_ | --identifier  | Trailing underscores disambiguate python identifiers from keywords.|
    | ident_ifier | --ident-ifier |                                                                    |
    """
    return f"--{field.name.rstrip('_').replace('_', '-')}"


strOpt = _t.Optional[str]
strListOpt = _t.Optional[_t.Union[str, list[str]]]
Value = _t.Union[bool,
                 strOpt,
                 strListOpt]


@_d.dataclass
class File:
    class Mode(_e.Enum):
        Input = 'input'
        Output = 'output'
    PATH_STDOUT: _t.ClassVar[str] = '-'

    class Encodings(_e.Enum):
        JSON = 'json'
        YAMl = 'yaml'
        TEXT = 'txt'
        UNSPECIFIED = None

        def to_args(self) -> list[str]:
            if self != self.UNSPECIFIED:
                return [f'{self.value}:']  # todo (ado) only valid for input
            return []

    path: str
    encoding: Encodings = Encodings.UNSPECIFIED

    def to_args(self, mode: Mode) -> list[str]:
        args = self.encoding.to_args() + [self.path]
        if mode == File.Mode.Output:
            return [''.join(args)]
        else:
            return args


@_d.dataclass
class Stdin:
    contents: str
    encoding: File.Encodings = File.Encodings.UNSPECIFIED
    path: _t.ClassVar[str] = '-'

    def encode(self) -> bytes:
        return self.contents.encode()

    def to_args(self, mode: File.Mode):
        return File.to_args(self, mode)


Input = _t.Union[Stdin, str]
FileStr = _t.Union[File, str, _pl.Path]
Files = _t.Union[FileStr, list[FileStr]]


class Cmd:
    class Flags:
        class _Flag:
            @staticmethod
            def value_to_args(flag, type_: _t.Type[Value], value: Value) -> list[str]:
                if type_ is bool and isinstance(value, bool):
                    if value:
                        return [flag]
                    return []
                if value is not None:  # note: incorrect types will flow through here
                    if isinstance(value, str):  # and (type_ in {strOpt, strArrayOpt}):
                        return [f"{flag}={value}"]
                    if type(value) is list:  # and type_ is list[str]:
                        return list(_it.chain.from_iterable(Cmd.Flags._Flag.value_to_args(flag, strOpt, v) for v in value))
                    raise ValueError(f'invalid: {flag}: {type_} = {value}')
                return []

            @staticmethod
            def field_to_args(field: _d.Field, value: Value) -> list[str]:
                flag = _field_name_flag(field)
                type_ = field.type
                return Cmd.Flags._Flag.value_to_args(flag, type_, value)

            def to_args(self) -> list[str]:
                fields: tuple[_d.Field] = _d.fields(self)
                values = (getattr(self, field.name) for field in fields)
                return list(
                    _it.chain.from_iterable(
                        map(lambda fv: Cmd.Flags._Flag.field_to_args(*fv), zip(fields, values))))

        @_d.dataclass
        class Global(_Flag):
            # todo (ado) help?
            all_errors: bool = False
            """print all available errors"""
            ignore: bool = False
            """proceed in the presence of errors"""
            simplify: bool = False
            """simplify output"""
            strict: bool = False
            """report errors for lossy mappings"""
            trace: bool = False
            """trace computation"""
            verbose: bool = False
            """print information about progress"""

        @_d.dataclass
        class Eval(_Flag):
            all: bool = False
            """show optional and hidden fields"""
            concrete: bool = False
            """require the evaluation to be concrete"""
            expression: strListOpt = None
            """evaluate this expression only"""
            help: bool = False
            """help for eval"""
            inject: strListOpt = None
            """set the value of a tagged field"""
            list_: bool = False
            """concatenate multiple objects into a list"""
            merge: bool = False  # todo (ado) defaults True. how does this actually work as a flag? does providing it reverse merge?
            """merge non-CUE files (default true)"""
            name: strOpt = None
            """glob filter for file names"""
            out: strOpt = None
            """output format (run 'cue filetypes' for more info)"""
            outfile: strOpt = None
            """filename or - for stdout with optional file prefix (run 'cue filetypes' for more info)"""
            package: strOpt = None
            """package name for non-CUE files"""
            path: strListOpt = None
            """CUE expression for single path component"""
            proto_path: strListOpt = None
            """paths in which to search for imports"""
            schema: strOpt = None
            """expression to select schema for evaluating values in non-CUE files"""
            show_attributes: bool = False
            """display field attributes"""
            show_hidden: bool = False
            """display hidden fields"""
            show_optional: bool = False
            """display optional fields"""
            with_context: bool = False
            """import as object with contextual data"""

        @_d.dataclass
        class Def(_Flag):
            expression: strListOpt = None
            """evaluate this expression only"""
            help: bool = False
            """help for eval"""
            inject: strListOpt = None
            """set the value of a tagged field"""
            list_: bool = False
            """concatenate multiple objects into a list"""
            merge: bool = False  # todo (ado) defaults True. how does this actually work as a flag? does providing it reverse merge?
            """merge non-CUE files (default true)"""
            name: strOpt = None
            """glob filter for file names"""
            out: strOpt = None
            """output format (run 'cue filetypes' for more info)"""
            outfile: strOpt = None
            """filename or - for stdout with optional file prefix (run 'cue filetypes' for more info)"""
            package: strOpt = None
            """package name for non-CUE files"""
            path: strListOpt = None
            """CUE expression for single path component"""
            proto_path: strListOpt = None
            """paths in which to search for imports"""
            schema: strOpt = None
            """expression to select schema for evaluating values in non-CUE files"""
            show_attributes: bool = False
            """display field attributes"""
            with_context: bool = False
            """import as object with contextual data"""

        @_d.dataclass
        class Vet(_Flag):
            concrete: bool = False
            """require the evaluation to be concrete"""
            help: bool = False
            """help for eval"""
            inject: strListOpt = None
            """set the value of a tagged field"""
            list_: bool = False
            """concatenate multiple objects into a list"""
            merge: bool = False  # todo (ado) defaults True. how does this actually work as a flag? does providing it reverse merge?
            """merge non-CUE files (default true)"""
            name: strOpt = None
            """glob filter for file names"""
            package: strOpt = None
            """package name for non-CUE files"""
            path: strListOpt = None
            """CUE expression for single path component"""
            proto_path: strListOpt = None
            """paths in which to search for imports"""
            schema: strOpt = None
            """expression to select schema for evaluating values in non-CUE files"""
            with_context: bool = False
            """import as object with contextual data"""

        CommandFlags = _t.Union[Eval, Vet]

        @staticmethod
        def parse(cmd: _t.Optional[CommandFlags], global_: _t.Optional[Global]) -> list[str]:
            args = [] if not cmd else cmd.to_args()
            return args + [] if not global_ else global_.to_args()

    @staticmethod
    def parse_file(file: File, mode: File.Mode) -> list[str]:
        if isinstance(file, File):
            return file.to_args(mode)
        return [str(file)]

    @staticmethod
    def parse_files(files: Files, mode: File.Mode) -> list[str]:
        if files:
            if isinstance(files, list):
                return list(_it.chain.from_iterable((Cmd.parse_file(file, mode) for file in files)))
            return Cmd.parse_file(files, mode)
        return []

    @staticmethod
    def cmd(cmd: str, input: Input = '', files: _t.Optional[Files] = None, *,
            flags_cmd: _t.Optional[Flags.CommandFlags] = None,
            flags_global: _t.Optional[Flags.Global] = None) -> str:
        run = _sp.run(['cue', cmd] +
                      Cmd.parse_files(files, File.Mode.Input) +
                      (['-'] if (type(input) is str)
                       else ([] if not input else
                             input.to_args(File.Mode.Input))) +
                      Cmd.Flags.parse(flags_cmd, flags_global),
                      input=input.encode(),
                      stdout=_sp.PIPE,
                      stderr=_sp.PIPE)
        CalledProcessError.check(run, input.encode())
        return run.stdout.decode()

    @staticmethod
    def eval(input: Input = '', files: _t.Optional[Files] = None, *,
             flags: _t.Optional[Flags.Eval] = None,
             flags_global: _t.Optional[Flags.Global] = None) -> str:
        """
        eval evaluates, validates, and prints a configuration.

        Printing is skipped if validation fails.

        The --expression flag is used to evaluate an expression within the
        configuration file, instead of the entire configuration file itself.

        >>> Cmd.eval(input='a: [ "a", "b", "c" ]', flags=Cmd.Flags.Eval(expression=['a[0]', 'a[1]']))
        "a"
        "c"

        """
        return Cmd.cmd('eval', input, files, flags_cmd=flags, flags_global=flags_global)

    def def_(input: Input = '', files: _t.Optional[Files] = None, *,
             flags: _t.Optional[Flags.Def] = None,
             flags_global: _t.Optional[Flags.Global] = None) -> str:
        return Cmd.cmd('def', input, files, flags_cmd=flags, flags_global=flags_global)

    @staticmethod
    def vet(input: Input = '',
            files: _t.Optional[Files] = None, *,
            flags: _t.Optional[Flags.Vet] = None,
            flags_global: _t.Optional[Flags.Global] = None):
        return Cmd.cmd('vet', input, files, flags_cmd=flags, flags_global=flags_global)


if __name__ == '__main__':
    # print(Flags.Eval(expression=['a[0]', 'a[1]'], concrete=True).to_args())
    print(Cmd.eval(input='a: [ "a", "b", "c" ]', flags=Cmd.Flags.Eval(expression=['a[0]', 'a[1]'])))
    print(Cmd.eval(input='a: [ "a", "b", "c" ]', flags=Cmd.Flags.Eval(expression='a[0]')))
    print(Cmd.eval(input='a: [ "a", "b", "c" ]\r\na: ["a", ...string]', flags=Cmd.Flags.Eval(expression='a[0]')))
    print(Cmd.eval(input=Stdin('a: [ "a", "b", "c" ]'), flags=Cmd.Flags.Eval(expression='a[0]')))
