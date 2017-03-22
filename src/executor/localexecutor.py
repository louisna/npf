import os
import signal
from multiprocessing import Queue
from subprocess import PIPE, Popen, TimeoutExpired


class LocalExecutor:
    def __init__(self):
        pass

    class LocalKiller:
        def __init__(self, pgpid):
            self.pgpid = pgpid

        def kill(self):
            os.killpg(self.pgpid, signal.SIGKILL)

    def exec(self, cmd, terminated_event, bin_path=None, queue: Queue = None, options = None, stdin = None, timeout = None):
        env = os.environ.copy()
        if (bin_path):
            env["PATH"] = bin_path + ":" + env["PATH"]
        if options is not None and options.show_cmd:
            print("Executing (PATH+=%s) :\n%s" % (bin_path, cmd))

        p = Popen(cmd,
                  stdin=PIPE, stdout=PIPE, stderr=PIPE,
                  shell=True, preexec_fn=os.setsid,
                  env=env)
        pid = p.pid
        pgpid = os.getpgid(pid)

        if queue:
            queue.put(LocalExecutor.LocalKiller(pgpid))
        try:
            s_output, s_err = [x.decode() for x in
                               p.communicate(input = stdin,  timeout=timeout)]
            p.stdin.close()
            p.stderr.close()
            p.stdout.close()
            return pid, s_output, s_err, p.returncode
        except TimeoutExpired:
            print("Test expired")
            p.terminate()
            p.kill()
            os.killpg(pgpid, signal.SIGKILL)
            os.killpg(pgpid, signal.SIGTERM)
            s_output, s_err = [x.decode() for x in p.communicate()]
            print(s_output)
            print(s_err)
            p.stdin.close()
            p.stderr.close()
            p.stdout.close()
            return 0, s_output, s_err, p.returncode
        except KeyboardInterrupt:
            os.killpg(pgpid, signal.SIGKILL)
            return -1, s_output, s_err, p.returncode
