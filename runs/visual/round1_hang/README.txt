Round 1 hang, third reproduction (ec221502 detached, scenario 1 at beauty, run 877a84dee403).
Last log line, 45 s in: LogFlightSimWeather cloud VolumetricCloudComponent (VolumetricCloud_0):
MID_M_FlightSimCloudLayers_0, domain 3, used_with_volumetric_cloud yes, compiled. Nothing after it.
60 s later: all 48 editor threads in Wait (mostly UserRequest), editor CPU ~1 s per 30 s, GPU 0 %.
No debugger (cdb/WinDbg) on this laptop, so no symbolized stacks. Thread table: threads.txt
(GetThreadDescription returns no names; UE names threads by the debugger exception).
Dumps written with dbghelp MiniDumpWriteDump, kept on the laptop, not committed:
  runs\visual\round1_hang\UnrealEditor-Cmd_hang_threads.dmp  (46 MB, threads + stacks memory)
  runs\visual\round1_hang\UnrealEditor-Cmd_hang_full.dmp     (5.1 GB, full memory)
The thread with the most CPU (17.4 s, id 13448) is probably the game thread.
