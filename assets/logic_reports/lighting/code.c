// 00041170  sim_analytics_recorder::flight_in_progress

/* sim_analytics_recorder::flight_in_progress() const */

undefined8 __thiscall sim_analytics_recorder::flight_in_progress(sim_analytics_recorder *this)

{
  long lVar1;
  
  lVar1 = *(long *)(this + 0x70);
  if (*(long *)(this + 0x68) != lVar1) {
    return CONCAT71((int7)((ulong)lVar1 >> 8),
                    *(double *)(lVar1 + -0x278) <= 0.0 && *(double *)(lVar1 + -0x278) != 0.0);
  }
  return 0;
}


// 00042600  sim_analytics_recorder::begin_freeflight

/* WARNING: Type propagation algorithm not settling */
/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* sim_analytics_recorder::begin_freeflight(veh_class const&, internal_new_flight_spec const&) */

void __thiscall
sim_analytics_recorder::begin_freeflight
          (sim_analytics_recorder *this,veh_class *param_1,internal_new_flight_spec *param_2)

{
  start_loc_spec *this_00;
  double *pdVar1;
  void *pvVar2;
  void *pvVar3;
  sim_analytics_recorder *psVar4;
  void *pvVar5;
  char cVar6;
  undefined4 uVar7;
  undefined4 uVar8;
  undefined4 uVar9;
  undefined4 uVar10;
  undefined4 uVar11;
  long lVar12;
  long lVar13;
  double dVar14;
  undefined1 auVar15 [16];
  undefined1 auVar16 [16];
  double local_318;
  undefined8 local_2f8;
  double dStack_2f0;
  undefined8 local_2e8;
  undefined2 local_2e0;
  undefined1 local_2de;
  ulong local_2dc;
  undefined4 uStack_2d4;
  undefined4 uStack_2d0;
  undefined4 uStack_2cc;
  void *local_2c8;
  aircraft_metadata local_2c0 [368];
  void *local_150;
  void *pvStack_148;
  undefined8 local_140;
  undefined8 uStack_138;
  undefined4 local_130;
  ulong local_128;
  undefined8 uStack_120;
  void *local_118;
  ulong uStack_110;
  undefined8 local_108;
  void *pvStack_100;
  ulong local_f8;
  undefined8 uStack_f0;
  void *local_e8;
  ulong uStack_e0;
  undefined8 local_d8;
  void *pvStack_d0;
  ulong local_c8;
  undefined8 uStack_c0;
  void *local_b8;
  byte local_b0;
  undefined4 local_af;
  undefined1 local_ab;
  void *local_a0;
  ulong local_98;
  undefined8 uStack_90;
  void *local_88;
  undefined8 local_80;
  undefined8 uStack_78;
  ulong local_70;
  undefined8 uStack_68;
  void *local_60;
  ulong local_58;
  undefined8 uStack_50;
  void *local_48;
  sim_analytics_recorder *local_38;
  
  if (*(int *)param_2 != 0) {
    return;
  }
  if ((*(long *)(this + 0x68) != *(long *)(this + 0x70)) &&
     (pdVar1 = (double *)(*(long *)(this + 0x70) + -0x278), *pdVar1 <= 0.0 && *pdVar1 != 0.0)) {
    lVar12 = std::chrono::system_clock::now();
    lVar12 = lVar12 / 1000000;
    auVar15._8_4_ = (int)((ulong)lVar12 >> 0x20);
    auVar15._0_8_ = lVar12;
    auVar15._12_4_ = _UNK_02520374;
    *(double *)(*(long *)(this + 0x70) + -0x280) =
         (auVar15._8_8_ - _UNK_02520388) +
         ((double)CONCAT44(_DAT_02520370,(int)lVar12) - _DAT_02520380);
    local_38 = (sim_analytics_recorder *)
               replay::manager::replay_end_time((manager *)&replay::s_manager);
    dVar14 = (double)replay::manager::replay_begin_time((manager *)&replay::s_manager);
    lVar12 = *(long *)(this + 0x70);
    *(double *)(lVar12 + -0x278) = (double)local_38 - dVar14;
    *(undefined4 *)(lVar12 + -0xfc) = 0;
  }
  local_58 = 0;
  uStack_50 = 0;
  local_48 = (void *)0x0;
  if (*(int *)(param_2 + 8) == 3) {
    std::string::assign((char *)&local_58);
  }
  else {
    this_00 = (start_loc_spec *)(param_2 + 0x10);
    lVar12 = start_loc_spec::get_start_airport(this_00);
    if (lVar12 == 0) {
      cVar6 = start_loc_spec::is_lle_start(this_00);
      if (cVar6 == '\0') {
        uVar7 = start_loc_spec::to_init_flt_enum(this_00);
        switch(uVar7) {
        case 0x13:
          std::string::assign((char *)&local_58);
          break;
        case 0x14:
          std::string::assign((char *)&local_58);
          break;
        case 0x15:
          std::string::assign((char *)&local_58);
          break;
        case 0x16:
          std::string::assign((char *)&local_58);
          break;
        case 0x1a:
          std::string::assign((char *)&local_58);
          break;
        case 0x1b:
          std::string::assign((char *)&local_58);
          break;
        case 0x1c:
          std::string::assign((char *)&local_58);
          break;
        case 0x1d:
          std::string::assign((char *)&local_58);
          break;
        case 0x1e:
          std::string::assign((char *)&local_58);
        }
      }
      else {
        start_loc_spec::get_approx_start_location();
        local_38 = (sim_analytics_recorder *)dStack_2f0;
        start_loc_spec::get_approx_start_location();
        stl_printf((char *)&local_70,"%d, %d",(ulong)(uint)(int)((double)local_38 + DAT_02520410),
                   (ulong)(uint)(int)(DAT_02520410 + local_318));
        if ((local_58 & 1) != 0) {
          operator_delete(local_48);
        }
        local_48 = local_60;
        local_58 = local_70;
        uStack_50 = uStack_68;
      }
    }
    else {
      std::string::assign((char *)&local_58);
    }
  }
  local_2f8 = _DAT_02520390;
  dStack_2f0 = (double)_UNK_02520398;
  local_2e8 = 0xbff0000000000000;
  local_2e0 = 0;
  local_2de = 0;
  local_2dc = 0;
  uStack_2d4 = 0;
  uStack_2d0 = 0;
  uStack_2cc = 0;
  local_2c8 = (void *)0x0;
  local_38 = this;
  aircraft_metadata::aircraft_metadata(local_2c0);
  local_c8 = 0;
  uStack_c0 = 0;
  local_d8 = 0;
  pvStack_d0 = (void *)0x0;
  local_e8 = (void *)0x0;
  uStack_e0 = 0;
  local_f8 = 0;
  uStack_f0 = 0;
  local_108 = 0;
  pvStack_100 = (void *)0x0;
  local_118 = (void *)0x0;
  uStack_110 = 0;
  local_128 = 0;
  uStack_120 = 0;
  local_b8 = (void *)0x0;
  local_150 = (void *)0x0;
  pvStack_148 = (void *)0x0;
  local_140 = 0;
  uStack_138 = 0;
  local_b0 = 8;
  local_af = 0x53574f4c;
  local_ab = 0;
  local_98 = 0;
  uStack_90 = 0;
  local_88 = (void *)0x0;
  local_80 = _DAT_025203a0;
  uStack_78 = _UNK_025203a8;
  local_130 = 0;
  std::vector<analytics_flight,std::allocator<analytics_flight>>::emplace_back<analytics_flight>
            ((vector<analytics_flight,std::allocator<analytics_flight>> *)(local_38 + 0x68),
             (analytics_flight *)&local_2f8);
  if ((local_98 & 1) != 0) {
    operator_delete(local_88);
  }
  if ((local_b0 & 1) != 0) {
    operator_delete(local_a0);
  }
  if ((local_c8 & 1) != 0) {
    operator_delete(local_b8);
  }
  if ((uStack_e0 & 1) != 0) {
    operator_delete(pvStack_d0);
  }
  if ((local_f8 & 1) != 0) {
    operator_delete(local_e8);
  }
  if ((uStack_110 & 1) != 0) {
    operator_delete(pvStack_100);
  }
  pvVar3 = local_150;
  if ((local_128 & 1) != 0) {
    operator_delete(local_118);
    pvVar3 = local_150;
  }
  local_150 = pvVar3;
  pvVar5 = pvStack_148;
  if (pvVar3 == (void *)0x0) {
    aircraft_metadata::~aircraft_metadata(local_2c0);
  }
  else {
    while (pvVar2 = pvVar5, pvVar2 != pvVar3) {
      pvVar5 = (void *)((long)pvVar2 + -0x20);
      if ((*(byte *)((long)pvVar2 + -0x18) & 1) != 0) {
        operator_delete(*(void **)((long)pvVar2 + -8));
      }
    }
    pvStack_148 = pvVar3;
    operator_delete(local_150);
    aircraft_metadata::~aircraft_metadata(local_2c0);
  }
  if ((local_2dc & 0x100000000) != 0) {
    operator_delete(local_2c8);
  }
  lVar13 = std::chrono::system_clock::now();
  psVar4 = local_38;
  lVar13 = lVar13 / 1000000;
  auVar16._8_4_ = (int)((ulong)lVar13 >> 0x20);
  auVar16._0_8_ = lVar13;
  auVar16._12_4_ = _UNK_02520374;
  lVar12 = *(long *)(local_38 + 0x70);
  *(double *)(lVar12 + -0x288) =
       (auVar16._8_8_ - _UNK_02520388) +
       ((double)CONCAT44(_DAT_02520370,(int)lVar13) - _DAT_02520380);
  *(undefined4 *)(lVar12 + -0x100) = 3;
  aircraft_metadata::aircraft_metadata((aircraft_metadata *)&local_2f8,param_1);
  aircraft_metadata::operator=
            ((aircraft_metadata *)(*(long *)(psVar4 + 0x70) + -0x250),
             (aircraft_metadata *)&local_2f8);
  aircraft_metadata::~aircraft_metadata((aircraft_metadata *)&local_2f8);
  uVar7 = start_loc_spec::to_init_flt_enum((start_loc_spec *)(param_2 + 0x10));
  lVar12 = *(long *)(psVar4 + 0x70);
  *(undefined4 *)(lVar12 + -0x26c) = uVar7;
  std::string::operator=((string *)(lVar12 + -0x268),(string *)&local_58);
  uVar7 = REN_setting_get_value_now(0xb);
  uVar8 = REN_setting_get_value_now(0xd);
  uVar9 = REN_setting_get_value_now(9);
  uVar10 = REN_setting_get_value_now(1);
  uVar11 = REN_setting_get_value_now(3);
  lVar12 = *(long *)(local_38 + 0x70);
  *(undefined4 *)(lVar12 + -0xf8) = uVar7;
  *(undefined4 *)(lVar12 + -0xf4) = uVar8;
  *(undefined4 *)(lVar12 + -0xf0) = uVar9;
  *(undefined4 *)(lVar12 + -0xec) = uVar10;
  *(undefined4 *)(lVar12 + -0xe8) = uVar11;
  *(byte *)(*(long *)(local_38 + 0x70) + -0x26e) = (byte)param_2[0x334] ^ 1;
  if ((local_58 & 1) != 0) {
    operator_delete(local_48);
  }
  return;
}


// 00042e70  std::vector<analytics_flight,std::allocator<analytics_flight>>::emplace_back<analytics_flight>

/* analytics_flight& std::vector<analytics_flight, std::allocator<analytics_flight>
   >::emplace_back<analytics_flight>(analytics_flight&&) */

analytics_flight * __thiscall
std::vector<analytics_flight,std::allocator<analytics_flight>>::emplace_back<analytics_flight>
          (vector<analytics_flight,std::allocator<analytics_flight>> *this,analytics_flight *param_1
          )

{
  analytics_flight *paVar1;
  long lVar2;
  long lVar3;
  analytics_flight *paVar4;
  vector<analytics_flight,std::allocator<analytics_flight>> *pvVar5;
  analytics_flight *this_00;
  analytics_flight *local_68;
  analytics_flight *local_60;
  analytics_flight *local_58;
  undefined8 local_50;
  vector<analytics_flight,std::allocator<analytics_flight>> *local_48;
  vector<analytics_flight,std::allocator<analytics_flight>> *local_40;
  void *local_38;
  
  paVar4 = *(analytics_flight **)(this + 8);
  if (paVar4 < *(analytics_flight **)(this + 0x10)) {
    paVar1 = (analytics_flight *)analytics_flight::analytics_flight(paVar4,param_1);
    *(analytics_flight **)(this + 8) = paVar4 + 0x288;
  }
  else {
    lVar3 = (long)paVar4 - *(long *)this >> 3;
    pvVar5 = (vector<analytics_flight,std::allocator<analytics_flight>> *)
             (lVar3 * 0x2c3f35ba781948b1 + 1);
    if ((vector<analytics_flight,std::allocator<analytics_flight>> *)0x6522c3f35ba781 < pvVar5) {
      __vector_base<analytics_flight,std::allocator<analytics_flight>>::__throw_length_error();
      pvVar5 = this;
LAB_00042fdf:
                    /* WARNING: Subroutine does not return */
      std::__throw_length_error((char *)pvVar5);
    }
    local_48 = this + 0x10;
    lVar2 = (long)*(analytics_flight **)(this + 0x10) - *(long *)this >> 3;
    local_40 = (vector<analytics_flight,std::allocator<analytics_flight>> *)
               (lVar2 * 0x587e6b74f0329162);
    if (local_40 < pvVar5) {
      local_40 = pvVar5;
    }
    if (0x329161f9add3bf < (ulong)(lVar2 * 0x2c3f35ba781948b1)) {
      local_40 = (vector<analytics_flight,std::allocator<analytics_flight>> *)0x6522c3f35ba781;
    }
    if (local_40 == (vector<analytics_flight,std::allocator<analytics_flight>> *)0x0) {
      local_38 = (void *)0x0;
    }
    else {
      pvVar5 = local_40;
      if ((vector<analytics_flight,std::allocator<analytics_flight>> *)0x6522c3f35ba781 < local_40)
      goto LAB_00042fdf;
      local_38 = operator_new((long)local_40 * 0x288);
    }
    this_00 = (analytics_flight *)(lVar3 * 8 + (long)local_38);
    analytics_flight::analytics_flight(this_00,param_1);
    local_68 = *(analytics_flight **)this;
    paVar4 = *(analytics_flight **)(this + 8);
    local_58 = local_68;
    paVar1 = this_00;
    if (paVar4 != local_68) {
      do {
        paVar1 = paVar1 + -0x288;
        paVar4 = paVar4 + -0x288;
        analytics_flight::analytics_flight(paVar1,paVar4);
      } while (paVar4 != local_68);
      local_68 = *(analytics_flight **)this;
      local_58 = *(analytics_flight **)(this + 8);
    }
    *(analytics_flight **)this = paVar1;
    *(analytics_flight **)(this + 8) = this_00 + 0x288;
    local_50 = *(undefined8 *)(this + 0x10);
    *(void **)(this + 0x10) = (void *)((long)local_38 + (long)local_40 * 0x288);
    local_60 = local_68;
    paVar1 = (analytics_flight *)
             __split_buffer<analytics_flight,std::allocator<analytics_flight>&>::~__split_buffer
                       ((__split_buffer<analytics_flight,std::allocator<analytics_flight>&> *)
                        &local_68);
  }
  return paVar1;
}


// 00043450  sim_analytics_recorder::freeflight_wrecked

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* sim_analytics_recorder::freeflight_wrecked() */

void __thiscall sim_analytics_recorder::freeflight_wrecked(sim_analytics_recorder *this)

{
  double *pdVar1;
  long lVar2;
  double dVar3;
  double dVar4;
  undefined1 auVar5 [16];
  
  if ((*(long *)(this + 0x68) != *(long *)(this + 0x70)) &&
     (pdVar1 = (double *)(*(long *)(this + 0x70) + -0x278), *pdVar1 <= 0.0 && *pdVar1 != 0.0)) {
    lVar2 = std::chrono::system_clock::now();
    lVar2 = lVar2 / 1000000;
    auVar5._8_4_ = (int)((ulong)lVar2 >> 0x20);
    auVar5._0_8_ = lVar2;
    auVar5._12_4_ = _UNK_02520374;
    *(double *)(*(long *)(this + 0x70) + -0x280) =
         (auVar5._8_8_ - _UNK_02520388) +
         ((double)CONCAT44(_DAT_02520370,(int)lVar2) - _DAT_02520380);
    dVar3 = (double)replay::manager::replay_end_time((manager *)&replay::s_manager);
    dVar4 = (double)replay::manager::replay_begin_time((manager *)&replay::s_manager);
    lVar2 = *(long *)(this + 0x70);
    *(double *)(lVar2 + -0x278) = dVar3 - dVar4;
    *(undefined4 *)(lVar2 + -0xfc) = 2;
  }
  return;
}


// 00043ef0  sim_analytics_recorder::register_flight_control_hardware

/* sim_analytics_recorder::register_flight_control_hardware(std::string const&, std::string const&,
   std::string const&) */

void __thiscall
sim_analytics_recorder::register_flight_control_hardware
          (sim_analytics_recorder *this,string *param_1,string *param_2,string *param_3)

{
  ulong uVar1;
  void *pvVar2;
  undefined8 *puVar3;
  byte bVar4;
  code *pcVar5;
  undefined8 uVar6;
  long lVar7;
  void *pvVar8;
  void *pvVar9;
  long lVar10;
  ulong uVar11;
  undefined8 *puVar12;
  undefined8 *puVar13;
  ulong local_78;
  undefined8 uStack_70;
  void *local_68;
  ulong local_60;
  undefined8 uStack_58;
  void *local_50;
  ulong local_48;
  undefined8 uStack_40;
  void *local_38;
  
  std::string::string((string *)&local_78,param_1);
  std::string::string((string *)&local_60,param_2);
  std::string::string((string *)&local_48,param_3);
  puVar13 = *(undefined8 **)(this + 0x88);
  if (puVar13 < *(undefined8 **)(this + 0x90)) {
    puVar13[2] = local_68;
    *puVar13 = local_78;
    puVar13[1] = uStack_70;
    local_78 = 0;
    uStack_70 = 0;
    local_68 = (void *)0x0;
    puVar13[5] = local_50;
    puVar13[3] = local_60;
    puVar13[4] = uStack_58;
    local_60 = 0;
    uStack_58 = 0;
    local_50 = (void *)0x0;
    puVar13[8] = local_38;
    puVar13[6] = local_48;
    puVar13[7] = uStack_40;
    local_48 = 0;
    uStack_40 = 0;
    local_38 = (void *)0x0;
    *(undefined8 **)(this + 0x88) = puVar13 + 9;
  }
  else {
    puVar12 = *(undefined8 **)(this + 0x80);
    lVar10 = (long)puVar13 - (long)puVar12 >> 3;
    uVar1 = lVar10 * -0x71c71c71c71c71c7 + 1;
    if (0x38e38e38e38e38e < uVar1) {
      std::__vector_base<analytics_hardware,std::allocator<analytics_hardware>>::
      __throw_length_error();
                    /* WARNING: Does not return */
      pcVar5 = (code *)invalidInstructionException();
      (*pcVar5)();
    }
    lVar7 = (long)*(undefined8 **)(this + 0x90) - (long)puVar12 >> 3;
    uVar11 = lVar7 * 0x1c71c71c71c71c72;
    if (uVar11 < uVar1) {
      uVar11 = uVar1;
    }
    if (0x1c71c71c71c71c6 < (ulong)(lVar7 * -0x71c71c71c71c71c7)) {
      uVar11 = 0x38e38e38e38e38e;
    }
    if (uVar11 == 0) {
      pvVar8 = (void *)0x0;
    }
    else {
      if (0x38e38e38e38e38e < uVar11) {
                    /* WARNING: Subroutine does not return */
        std::__throw_length_error((char *)(this + 0x80));
      }
      pvVar8 = operator_new(uVar11 * 0x48);
    }
    pvVar9 = (void *)((long)pvVar8 + lVar10 * 8);
    pvVar2 = (void *)((long)pvVar8 + uVar11 * 0x48);
    *(void **)((long)pvVar8 + lVar10 * 8 + 0x10) = local_68;
    puVar3 = (undefined8 *)((long)pvVar8 + lVar10 * 8);
    *puVar3 = local_78;
    puVar3[1] = uStack_70;
    local_78 = 0;
    uStack_70 = 0;
    local_68 = (void *)0x0;
    *(void **)((long)pvVar8 + lVar10 * 8 + 0x28) = local_50;
    puVar3 = (undefined8 *)((long)pvVar8 + lVar10 * 8 + 0x18);
    *puVar3 = local_60;
    puVar3[1] = uStack_58;
    local_60 = 0;
    uStack_58 = 0;
    local_50 = (void *)0x0;
    *(void **)((long)pvVar8 + lVar10 * 8 + 0x40) = local_38;
    puVar3 = (undefined8 *)((long)pvVar8 + lVar10 * 8 + 0x30);
    *puVar3 = local_48;
    puVar3[1] = uStack_40;
    local_48 = 0;
    uStack_40 = 0;
    local_38 = (void *)0x0;
    lVar10 = (long)pvVar8 + lVar10 * 8 + 0x48;
    if (puVar13 == puVar12) {
      *(void **)(this + 0x80) = pvVar9;
      *(long *)(this + 0x88) = lVar10;
      *(void **)(this + 0x90) = pvVar2;
    }
    else {
      do {
        *(undefined8 *)((long)pvVar9 + -0x38) = puVar13[-7];
        uVar6 = puVar13[-8];
        *(undefined8 *)((long)pvVar9 + -0x48) = puVar13[-9];
        *(undefined8 *)((long)pvVar9 + -0x40) = uVar6;
        puVar13[-9] = 0;
        puVar13[-8] = 0;
        puVar13[-7] = 0;
        *(undefined8 *)((long)pvVar9 + -0x20) = puVar13[-4];
        uVar6 = puVar13[-5];
        *(undefined8 *)((long)pvVar9 + -0x30) = puVar13[-6];
        *(undefined8 *)((long)pvVar9 + -0x28) = uVar6;
        puVar13[-6] = 0;
        puVar13[-5] = 0;
        puVar13[-4] = 0;
        *(undefined8 *)((long)pvVar9 + -8) = puVar13[-1];
        uVar6 = puVar13[-2];
        *(undefined8 *)((long)pvVar9 + -0x18) = puVar13[-3];
        *(undefined8 *)((long)pvVar9 + -0x10) = uVar6;
        pvVar9 = (void *)((long)pvVar9 + -0x48);
        puVar13[-3] = 0;
        puVar13[-2] = 0;
        puVar13[-1] = 0;
        puVar13 = puVar13 + -9;
      } while (puVar13 != puVar12);
      puVar13 = *(undefined8 **)(this + 0x80);
      puVar12 = *(undefined8 **)(this + 0x88);
      *(void **)(this + 0x80) = pvVar9;
      *(long *)(this + 0x88) = lVar10;
      *(void **)(this + 0x90) = pvVar2;
      for (; puVar12 != puVar13; puVar12 = puVar12 + -9) {
        if ((*(byte *)(puVar12 + -3) & 1) == 0) {
          if ((*(byte *)(puVar12 + -6) & 1) == 0) goto LAB_00044174;
LAB_0004418f:
          operator_delete((void *)puVar12[-4]);
          bVar4 = *(byte *)(puVar12 + -9);
        }
        else {
          operator_delete((void *)puVar12[-1]);
          if ((*(byte *)(puVar12 + -6) & 1) != 0) goto LAB_0004418f;
LAB_00044174:
          bVar4 = *(byte *)(puVar12 + -9);
        }
        if ((bVar4 & 1) != 0) {
          operator_delete((void *)puVar12[-7]);
        }
      }
    }
    if (puVar13 != (undefined8 *)0x0) {
      operator_delete(puVar13);
    }
  }
  if ((local_48 & 1) != 0) {
    operator_delete(local_38);
  }
  if ((local_60 & 1) != 0) {
    operator_delete(local_50);
  }
  if ((local_78 & 1) != 0) {
    operator_delete(local_68);
  }
  return;
}


// 00044290  sim_analytics_recorder::begin_flight

/* sim_analytics_recorder::begin_flight(SIM_mission const*) */

void __thiscall
sim_analytics_recorder::begin_flight(sim_analytics_recorder *this,SIM_mission *param_1)

{
  begin_flight_internal(this,param_1,false);
  return;
}


// 000442a0  sim_analytics_recorder::begin_flight_internal

/* WARNING: Type propagation algorithm not settling */
/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* sim_analytics_recorder::begin_flight_internal(SIM_mission const*, bool) */

void __thiscall
sim_analytics_recorder::begin_flight_internal
          (sim_analytics_recorder *this,SIM_mission *param_1,bool param_2)

{
  double *pdVar1;
  void *pvVar2;
  void *pvVar3;
  sim_analytics_recorder *psVar4;
  void *pvVar5;
  char cVar6;
  undefined4 uVar7;
  undefined4 uVar8;
  undefined4 uVar9;
  undefined4 uVar10;
  undefined4 uVar11;
  long lVar12;
  aircraft_manager *this_00;
  string *psVar13;
  aircraft_metadata *paVar14;
  double dVar15;
  undefined1 auVar16 [16];
  undefined1 auVar17 [16];
  undefined8 local_4b8;
  undefined8 uStack_4b0;
  undefined8 local_4a8;
  undefined2 local_4a0;
  undefined1 local_49e;
  ulong local_49c;
  undefined4 uStack_494;
  undefined4 uStack_490;
  undefined4 uStack_48c;
  void *local_488;
  aircraft_metadata local_480 [368];
  void *local_310;
  void *pvStack_308;
  undefined8 local_300;
  undefined8 uStack_2f8;
  undefined4 local_2f0;
  ulong local_2e8;
  undefined8 uStack_2e0;
  void *local_2d8;
  ulong uStack_2d0;
  undefined8 local_2c8;
  void *pvStack_2c0;
  ulong local_2b8;
  undefined8 uStack_2b0;
  void *local_2a8;
  ulong uStack_2a0;
  undefined8 local_298;
  void *pvStack_290;
  ulong local_288;
  undefined8 uStack_280;
  void *local_278;
  byte local_270;
  undefined4 local_26f;
  undefined1 local_26b;
  void *local_260;
  ulong local_258;
  undefined8 uStack_250;
  void *local_248;
  undefined8 local_240;
  undefined8 uStack_238;
  double local_40;
  sim_analytics_recorder *local_38;
  
  if ((*(long *)(this + 0x68) != *(long *)(this + 0x70)) &&
     (pdVar1 = (double *)(*(long *)(this + 0x70) + -0x278), *pdVar1 <= 0.0 && *pdVar1 != 0.0)) {
    lVar12 = std::chrono::system_clock::now();
    lVar12 = lVar12 / 1000000;
    auVar16._8_4_ = (int)((ulong)lVar12 >> 0x20);
    auVar16._0_8_ = lVar12;
    auVar16._12_4_ = _UNK_02520374;
    *(double *)(*(long *)(this + 0x70) + -0x280) =
         (auVar16._8_8_ - _UNK_02520388) +
         ((double)CONCAT44(_DAT_02520370,(int)lVar12) - _DAT_02520380);
    local_40 = (double)replay::manager::replay_end_time((manager *)&replay::s_manager);
    dVar15 = (double)replay::manager::replay_begin_time((manager *)&replay::s_manager);
    lVar12 = *(long *)(this + 0x70);
    *(double *)(lVar12 + -0x278) = local_40 - dVar15;
    *(undefined4 *)(lVar12 + -0xfc) = 0;
  }
  local_4b8 = _DAT_02520390;
  uStack_4b0 = _UNK_02520398;
  local_4a8 = 0xbff0000000000000;
  local_4a0 = 0;
  local_49e = 0;
  local_49c = 0;
  uStack_494 = 0;
  uStack_490 = 0;
  uStack_48c = 0;
  local_488 = (void *)0x0;
  aircraft_metadata::aircraft_metadata(local_480);
  local_288 = 0;
  uStack_280 = 0;
  local_298 = 0;
  pvStack_290 = (void *)0x0;
  local_2a8 = (void *)0x0;
  uStack_2a0 = 0;
  local_2b8 = 0;
  uStack_2b0 = 0;
  local_2c8 = 0;
  pvStack_2c0 = (void *)0x0;
  local_2d8 = (void *)0x0;
  uStack_2d0 = 0;
  local_2e8 = 0;
  uStack_2e0 = 0;
  local_278 = (void *)0x0;
  local_310 = (void *)0x0;
  pvStack_308 = (void *)0x0;
  local_300 = 0;
  uStack_2f8 = 0;
  local_270 = 8;
  local_26f = 0x53574f4c;
  local_26b = 0;
  local_258 = 0;
  uStack_250 = 0;
  local_248 = (void *)0x0;
  local_240 = _DAT_025203a0;
  uStack_238 = _UNK_025203a8;
  local_2f0 = 0;
  std::vector<analytics_flight,std::allocator<analytics_flight>>::emplace_back<analytics_flight>
            ((vector<analytics_flight,std::allocator<analytics_flight>> *)(this + 0x68),
             (analytics_flight *)&local_4b8);
  if ((local_258 & 1) != 0) {
    operator_delete(local_248);
  }
  if ((local_270 & 1) != 0) {
    operator_delete(local_260);
  }
  if ((local_288 & 1) != 0) {
    operator_delete(local_278);
  }
  if ((uStack_2a0 & 1) != 0) {
    operator_delete(pvStack_290);
  }
  if ((local_2b8 & 1) != 0) {
    operator_delete(local_2a8);
  }
  if ((uStack_2d0 & 1) != 0) {
    operator_delete(pvStack_2c0);
  }
  pvVar3 = local_310;
  if ((local_2e8 & 1) != 0) {
    operator_delete(local_2d8);
    pvVar3 = local_310;
  }
  local_310 = pvVar3;
  pvVar5 = pvStack_308;
  if (pvVar3 == (void *)0x0) {
    aircraft_metadata::~aircraft_metadata(local_480);
  }
  else {
    while (pvVar2 = pvVar5, pvVar2 != pvVar3) {
      pvVar5 = (void *)((long)pvVar2 + -0x20);
      if ((*(byte *)((long)pvVar2 + -0x18) & 1) != 0) {
        operator_delete(*(void **)((long)pvVar2 + -8));
      }
    }
    pvStack_308 = pvVar3;
    operator_delete(local_310);
    aircraft_metadata::~aircraft_metadata(local_480);
  }
  if ((local_49c & 0x100000000) != 0) {
    operator_delete(local_488);
  }
  lVar12 = std::chrono::system_clock::now();
  lVar12 = lVar12 / 1000000;
  auVar17._8_4_ = (int)((ulong)lVar12 >> 0x20);
  auVar17._0_8_ = lVar12;
  auVar17._12_4_ = _UNK_02520374;
  *(double *)(*(long *)(this + 0x70) + -0x288) =
       (auVar17._8_8_ - _UNK_02520388) +
       ((double)CONCAT44(_DAT_02520370,(int)lVar12) - _DAT_02520380);
  this_00 = (aircraft_manager *)aircraft_manager::instance();
  psVar13 = (string *)SIM_mission::get_aircraft_p0(param_1);
  paVar14 = (aircraft_metadata *)aircraft_manager::get_aircraft_by_path(this_00,psVar13);
  aircraft_metadata::operator=((aircraft_metadata *)(*(long *)(this + 0x70) + -0x250),paVar14);
  *(bool *)(*(long *)(this + 0x70) + -0x270) = param_2;
  cVar6 = SIM_mission::IsTutorial(param_1);
  local_38 = this;
  if (cVar6 == '\0') {
    cVar6 = SIM_mission::IsChallenge(param_1);
    if (cVar6 == '\0') {
      cVar6 = SIM_mission::IsTestFlight();
      lVar12 = *(long *)(this + 0x70);
      if (cVar6 == '\0') {
        *(undefined4 *)(lVar12 + -0x100) = 1;
      }
      else {
        *(undefined4 *)(lVar12 + -0x100) = 5;
      }
    }
    else {
      lVar12 = *(long *)(this + 0x70);
      *(undefined4 *)(lVar12 + -0x100) = 2;
    }
  }
  else {
    lVar12 = *(long *)(this + 0x70);
    *(undefined4 *)(lVar12 + -0x100) = 6;
  }
  *(SIM_mission **)(lVar12 + -200) = param_1;
  uVar7 = REN_setting_get_value_now(0xb);
  uVar8 = REN_setting_get_value_now(0xd);
  uVar9 = REN_setting_get_value_now(9);
  uVar10 = REN_setting_get_value_now(1);
  uVar11 = REN_setting_get_value_now(3);
  lVar12 = *(long *)(local_38 + 0x70);
  *(undefined4 *)(lVar12 + -0xf8) = uVar7;
  *(undefined4 *)(lVar12 + -0xf4) = uVar8;
  *(undefined4 *)(lVar12 + -0xf0) = uVar9;
  *(undefined4 *)(lVar12 + -0xec) = uVar10;
  *(undefined4 *)(lVar12 + -0xe8) = uVar11;
  SIM_mission::get_flight_spec();
  uVar7 = start_loc_spec::to_init_flt_enum((start_loc_spec *)&local_4b8);
  psVar4 = local_38;
  *(undefined4 *)(*(long *)(local_38 + 0x70) + -0x26c) = uVar7;
  flight_spec::~flight_spec((flight_spec *)&local_4b8);
  SIM_mission::get_flight_spec();
  lVar12 = get_nearest_airport(&local_4b8,7);
  flight_spec::~flight_spec((flight_spec *)&local_4b8);
  if (lVar12 != 0) {
    std::string::assign((char *)(*(long *)(psVar4 + 0x70) + -0x268));
  }
  return;
}


// 00044980  sim_analytics_recorder::retry_flight

/* sim_analytics_recorder::retry_flight(SIM_mission const*) */

void __thiscall
sim_analytics_recorder::retry_flight(sim_analytics_recorder *this,SIM_mission *param_1)

{
  begin_flight_internal(this,param_1,true);
  return;
}


// 00044ba0  sim_analytics_recorder::end_flight

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* sim_analytics_recorder::end_flight(mission_end_type_t, std::string const&) */

void sim_analytics_recorder::end_flight(long param_1,undefined4 param_2)

{
  double *pdVar1;
  long lVar2;
  double dVar3;
  double dVar4;
  undefined1 auVar5 [16];
  
  if ((*(long *)(param_1 + 0x68) != *(long *)(param_1 + 0x70)) &&
     (pdVar1 = (double *)(*(long *)(param_1 + 0x70) + -0x278), *pdVar1 <= 0.0 && *pdVar1 != 0.0)) {
    lVar2 = std::chrono::system_clock::now();
    lVar2 = lVar2 / 1000000;
    auVar5._8_4_ = (int)((ulong)lVar2 >> 0x20);
    auVar5._0_8_ = lVar2;
    auVar5._12_4_ = _UNK_02520374;
    *(double *)(*(long *)(param_1 + 0x70) + -0x280) =
         (auVar5._8_8_ - _UNK_02520388) +
         ((double)CONCAT44(_DAT_02520370,(int)lVar2) - _DAT_02520380);
    dVar3 = (double)replay::manager::replay_end_time((manager *)&replay::s_manager);
    dVar4 = (double)replay::manager::replay_begin_time((manager *)&replay::s_manager);
    lVar2 = *(long *)(param_1 + 0x70);
    *(double *)(lVar2 + -0x278) = dVar3 - dVar4;
    *(undefined4 *)(lVar2 + -0xfc) = param_2;
  }
  return;
}


// 00044c60  sim_analytics_recorder::begin_flight_lesson

/* WARNING: Type propagation algorithm not settling */
/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* sim_analytics_recorder::begin_flight_lesson(ozflite_metadata const&) */

void __thiscall
sim_analytics_recorder::begin_flight_lesson(sim_analytics_recorder *this,ozflite_metadata *param_1)

{
  string *psVar1;
  double *pdVar2;
  undefined8 uVar3;
  void *pvVar4;
  void *pvVar5;
  ozflite_metadata *poVar6;
  void *pvVar7;
  undefined4 uVar8;
  undefined4 uVar9;
  undefined4 uVar10;
  undefined4 uVar11;
  long lVar12;
  aircraft_manager *this_00;
  aircraft_metadata *paVar13;
  double dVar14;
  undefined1 auVar15 [16];
  undefined1 auVar16 [16];
  undefined8 local_2d8;
  undefined8 uStack_2d0;
  undefined8 local_2c8;
  undefined2 local_2c0;
  undefined1 local_2be;
  ulong local_2bc;
  undefined4 uStack_2b4;
  undefined4 uStack_2b0;
  undefined4 uStack_2ac;
  void *local_2a8;
  aircraft_metadata local_2a0 [368];
  void *local_130;
  void *pvStack_128;
  undefined8 local_120;
  undefined8 uStack_118;
  undefined4 local_110;
  ulong local_108;
  undefined8 uStack_100;
  void *local_f8;
  ulong uStack_f0;
  undefined8 local_e8;
  void *pvStack_e0;
  ulong local_d8;
  undefined8 uStack_d0;
  void *local_c8;
  ulong uStack_c0;
  undefined8 local_b8;
  void *pvStack_b0;
  ulong local_a8;
  undefined8 uStack_a0;
  void *local_98;
  byte local_90;
  undefined4 local_8f;
  undefined1 local_8b;
  void *local_80;
  ulong local_78;
  undefined8 uStack_70;
  void *local_68;
  undefined8 local_60;
  undefined8 uStack_58;
  ozflite_metadata *local_48;
  undefined4 local_3c;
  string *local_38;
  
  local_48 = param_1;
  if ((*(long *)(this + 0x68) != *(long *)(this + 0x70)) &&
     (pdVar2 = (double *)(*(long *)(this + 0x70) + -0x278), *pdVar2 <= 0.0 && *pdVar2 != 0.0)) {
    lVar12 = std::chrono::system_clock::now();
    lVar12 = lVar12 / 1000000;
    auVar15._8_4_ = (int)((ulong)lVar12 >> 0x20);
    auVar15._0_8_ = lVar12;
    auVar15._12_4_ = _UNK_02520374;
    *(double *)(*(long *)(this + 0x70) + -0x280) =
         (auVar15._8_8_ - _UNK_02520388) +
         ((double)CONCAT44(_DAT_02520370,(int)lVar12) - _DAT_02520380);
    local_38 = (string *)replay::manager::replay_end_time((manager *)&replay::s_manager);
    dVar14 = (double)replay::manager::replay_begin_time((manager *)&replay::s_manager);
    lVar12 = *(long *)(this + 0x70);
    *(double *)(lVar12 + -0x278) = (double)local_38 - dVar14;
    *(undefined4 *)(lVar12 + -0xfc) = 0;
  }
  local_2d8 = _DAT_02520390;
  uStack_2d0 = _UNK_02520398;
  local_2c8 = 0xbff0000000000000;
  local_2c0 = 0;
  local_2be = 0;
  local_2bc = 0;
  uStack_2b4 = 0;
  uStack_2b0 = 0;
  uStack_2ac = 0;
  local_2a8 = (void *)0x0;
  aircraft_metadata::aircraft_metadata(local_2a0);
  local_a8 = 0;
  uStack_a0 = 0;
  local_b8 = 0;
  pvStack_b0 = (void *)0x0;
  local_c8 = (void *)0x0;
  uStack_c0 = 0;
  local_d8 = 0;
  uStack_d0 = 0;
  local_e8 = 0;
  pvStack_e0 = (void *)0x0;
  local_f8 = (void *)0x0;
  uStack_f0 = 0;
  local_108 = 0;
  uStack_100 = 0;
  local_98 = (void *)0x0;
  local_130 = (void *)0x0;
  pvStack_128 = (void *)0x0;
  local_120 = 0;
  uStack_118 = 0;
  local_90 = 8;
  local_8f = 0x53574f4c;
  local_8b = 0;
  local_78 = 0;
  uStack_70 = 0;
  local_68 = (void *)0x0;
  local_60 = _DAT_025203a0;
  uStack_58 = _UNK_025203a8;
  local_110 = 0;
  std::vector<analytics_flight,std::allocator<analytics_flight>>::emplace_back<analytics_flight>
            ((vector<analytics_flight,std::allocator<analytics_flight>> *)(this + 0x68),
             (analytics_flight *)&local_2d8);
  if ((local_78 & 1) != 0) {
    operator_delete(local_68);
  }
  if ((local_90 & 1) != 0) {
    operator_delete(local_80);
  }
  if ((local_a8 & 1) != 0) {
    operator_delete(local_98);
  }
  if ((uStack_c0 & 1) != 0) {
    operator_delete(pvStack_b0);
  }
  if ((local_d8 & 1) != 0) {
    operator_delete(local_c8);
  }
  if ((uStack_f0 & 1) != 0) {
    operator_delete(pvStack_e0);
  }
  pvVar5 = local_130;
  if ((local_108 & 1) != 0) {
    operator_delete(local_f8);
    pvVar5 = local_130;
  }
  pvVar7 = pvStack_128;
  local_130 = pvVar5;
  if (pvVar5 == (void *)0x0) {
    aircraft_metadata::~aircraft_metadata(local_2a0);
  }
  else {
    while (pvVar4 = pvVar7, pvVar4 != pvVar5) {
      pvVar7 = (void *)((long)pvVar4 + -0x20);
      if ((*(byte *)((long)pvVar4 + -0x18) & 1) != 0) {
        operator_delete(*(void **)((long)pvVar4 + -8));
      }
    }
    pvStack_128 = pvVar5;
    operator_delete(local_130);
    aircraft_metadata::~aircraft_metadata(local_2a0);
  }
  if ((local_2bc & 0x100000000) != 0) {
    operator_delete(local_2a8);
  }
  lVar12 = std::chrono::system_clock::now();
  lVar12 = lVar12 / 1000000;
  auVar16._8_4_ = (int)((ulong)lVar12 >> 0x20);
  auVar16._0_8_ = lVar12;
  auVar16._12_4_ = _UNK_02520374;
  *(double *)(*(long *)(this + 0x70) + -0x288) =
       (auVar16._8_8_ - _UNK_02520388) +
       ((double)CONCAT44(_DAT_02520370,(int)lVar12) - _DAT_02520380);
  this_00 = (aircraft_manager *)aircraft_manager::instance();
  poVar6 = local_48;
  psVar1 = (string *)(local_48 + 0x68);
  paVar13 = (aircraft_metadata *)aircraft_manager::get_aircraft_by_path(this_00,psVar1);
  aircraft_metadata::operator=((aircraft_metadata *)(*(long *)(this + 0x70) + -0x250),paVar13);
  lVar12 = *(long *)(this + 0x70);
  *(undefined4 *)(lVar12 + -0x100) = 7;
  *(undefined4 *)(lVar12 + -0xc0) = *(undefined4 *)poVar6;
  std::string::operator=((string *)(lVar12 + -0xb8),(string *)(poVar6 + 8));
  std::string::operator=((string *)(lVar12 + -0xa0),(string *)(poVar6 + 0x20));
  std::string::operator=((string *)(lVar12 + -0x88),(string *)(poVar6 + 0x38));
  std::string::operator=((string *)(lVar12 + -0x70),(string *)(poVar6 + 0x50));
  std::string::operator=((string *)(lVar12 + -0x58),psVar1);
  local_38 = (string *)(poVar6 + 0x80);
  std::string::operator=((string *)(lVar12 + -0x40),local_38);
  std::string::operator=((string *)(lVar12 + -0x28),(string *)(poVar6 + 0x98));
  uVar3 = *(undefined8 *)(poVar6 + 0xb8);
  *(undefined8 *)(lVar12 + -0x10) = *(undefined8 *)(poVar6 + 0xb0);
  *(undefined8 *)(lVar12 + -8) = uVar3;
  local_3c = REN_setting_get_value_now(0xb);
  uVar8 = REN_setting_get_value_now(0xd);
  uVar9 = REN_setting_get_value_now(9);
  uVar10 = REN_setting_get_value_now(1);
  uVar11 = REN_setting_get_value_now(3);
  lVar12 = *(long *)(this + 0x70);
  *(undefined4 *)(lVar12 + -0xf8) = local_3c;
  *(undefined4 *)(lVar12 + -0xf4) = uVar8;
  *(undefined4 *)(lVar12 + -0xf0) = uVar9;
  *(undefined4 *)(lVar12 + -0xec) = uVar10;
  *(undefined4 *)(lVar12 + -0xe8) = uVar11;
  lVar12 = *(long *)(this + 0x70);
  *(undefined4 *)(lVar12 + -0x26c) = *(undefined4 *)(poVar6 + 0xb0);
  std::string::operator=((string *)(lVar12 + -0x268),local_38);
  return;
}


// 000452a0  sim_analytics_recorder::end_flight_lesson

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* sim_analytics_recorder::end_flight_lesson(mission_end_type_t) */

void __thiscall
sim_analytics_recorder::end_flight_lesson(sim_analytics_recorder *this,undefined4 param_2)

{
  double *pdVar1;
  long lVar2;
  double dVar3;
  double dVar4;
  undefined1 auVar5 [16];
  
  if ((*(long *)(this + 0x68) != *(long *)(this + 0x70)) &&
     (pdVar1 = (double *)(*(long *)(this + 0x70) + -0x278), *pdVar1 <= 0.0 && *pdVar1 != 0.0)) {
    lVar2 = std::chrono::system_clock::now();
    lVar2 = lVar2 / 1000000;
    auVar5._8_4_ = (int)((ulong)lVar2 >> 0x20);
    auVar5._0_8_ = lVar2;
    auVar5._12_4_ = _UNK_02520374;
    *(double *)(*(long *)(this + 0x70) + -0x280) =
         (auVar5._8_8_ - _UNK_02520388) +
         ((double)CONCAT44(_DAT_02520370,(int)lVar2) - _DAT_02520380);
    dVar3 = (double)replay::manager::replay_end_time((manager *)&replay::s_manager);
    dVar4 = (double)replay::manager::replay_begin_time((manager *)&replay::s_manager);
    lVar2 = *(long *)(this + 0x70);
    *(double *)(lVar2 + -0x278) = dVar3 - dVar4;
    *(undefined4 *)(lVar2 + -0xfc) = param_2;
  }
  return;
}


// 000490c0  flight_spec::~flight_spec

/* flight_spec::~flight_spec() */

void __thiscall flight_spec::~flight_spec(flight_spec *this)

{
  void *pvVar1;
  undefined8 *puVar2;
  undefined8 *puVar3;
  void *pvVar4;
  void *pvVar5;
  undefined1 local_30 [8];
  
  if ((this[0x468] != (flight_spec)0x0) &&
     (pvVar1 = *(void **)(this + 0x450), pvVar1 != (void *)0x0)) {
    pvVar5 = pvVar1;
    pvVar4 = *(void **)(this + 0x458);
    if (*(void **)(this + 0x458) != pvVar1) {
      do {
        pvVar5 = (void *)((long)pvVar4 + -0x40);
        if (*(char *)((long)pvVar4 + -8) != '\0') {
          if ((*(byte *)((long)pvVar4 + -0x20) & 1) != 0) {
            operator_delete(*(void **)((long)pvVar4 + -0x10));
          }
          if ((*(byte *)((long)pvVar4 + -0x38) & 1) != 0) {
            operator_delete(*(void **)((long)pvVar4 + -0x28));
          }
        }
        pvVar4 = pvVar5;
      } while (pvVar5 != pvVar1);
      pvVar5 = *(void **)(this + 0x450);
    }
    *(void **)(this + 0x458) = pvVar1;
    operator_delete(pvVar5);
  }
  if (this[0x270] != (flight_spec)0x0) {
    if (*(flight_spec **)(this + 0x238) != this + 0x250) {
      _free(*(flight_spec **)(this + 0x238));
    }
    if ((this[0x1e8] != (flight_spec)0x0) && (((byte)this[0x1c8] & 1) != 0)) {
      operator_delete(*(void **)(this + 0x1d8));
    }
  }
  if (this[400] != (flight_spec)0x0) {
    std::
    __tree<std::__value_type<int,std::string>,std::__map_value_compare<int,std::__value_type<int,std::string>,std::less<int>,true>,std::allocator<std::__value_type<int,std::string>>>
    ::destroy((__tree<std::__value_type<int,std::string>,std::__map_value_compare<int,std::__value_type<int,std::string>,std::less<int>,true>,std::allocator<std::__value_type<int,std::string>>>
               *)(this + 0x178),*(__tree_node **)(this + 0x180));
  }
  if (this[0x170] != (flight_spec)0x0) {
    if (((byte)this[0x150] & 1) != 0) {
      operator_delete(*(void **)(this + 0x160));
    }
    if (((byte)this[0x138] & 1) != 0) {
      operator_delete(*(void **)(this + 0x148));
    }
  }
  if (this[0x130] != (flight_spec)0x0) {
    if (((byte)this[0x118] & 1) != 0) {
      operator_delete(*(void **)(this + 0x128));
    }
    if (((byte)this[0x100] & 1) != 0) {
      operator_delete(*(void **)(this + 0x110));
    }
  }
  if (this[0xf0] != (flight_spec)0x0) {
    puVar3 = *(undefined8 **)(this + 0xd0);
    while (puVar3 != (undefined8 *)0x0) {
      puVar2 = (undefined8 *)*puVar3;
      operator_delete(puVar3);
      puVar3 = puVar2;
    }
    pvVar1 = *(void **)(this + 0xc0);
    *(undefined8 *)(this + 0xc0) = 0;
    if (pvVar1 != (void *)0x0) {
      operator_delete(pvVar1);
    }
    pvVar1 = *(void **)(this + 0xa8);
    if (pvVar1 != (void *)0x0) {
      *(void **)(this + 0xb0) = pvVar1;
      operator_delete(pvVar1);
    }
  }
  if (this[0x98] != (flight_spec)0x0) {
    if (((byte)this[0x80] & 1) != 0) {
      operator_delete(*(void **)(this + 0x90));
    }
    if (((byte)this[0x68] & 1) != 0) {
      operator_delete(*(void **)(this + 0x78));
    }
  }
  if (this[0x60] != (flight_spec)0x0) {
    if ((ulong)*(uint *)(this + 0x58) != 0xffffffff) {
      (*(code *)(&
                PTR___dispatch<std::__variant_detail::__dtor<std::__variant_detail::__traits<runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>,(std::__variant_detail::_Trait)1>::__destroy()::_lambda(auto:1&)_1_&&,std::__variant_detail::__base<(std::__variant_detail::_Trait)1,runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>&>_02ac5888
                )[*(uint *)(this + 0x58)])(local_30,this);
    }
    *(undefined4 *)(this + 0x58) = 0xffffffff;
  }
  return;
}


// 00049a30  std::__vector_base<analytics_flight,std::allocator<analytics_flight>>::~__vector_base

/* std::__vector_base<analytics_flight, std::allocator<analytics_flight> >::~__vector_base() */

void __thiscall
std::__vector_base<analytics_flight,std::allocator<analytics_flight>>::~__vector_base
          (__vector_base<analytics_flight,std::allocator<analytics_flight>> *this)

{
  void *pvVar1;
  void *pvVar2;
  void *pvVar3;
  void *pvVar4;
  void *pvVar5;
  
  pvVar1 = *(void **)this;
  if (pvVar1 == (void *)0x0) {
    return;
  }
  pvVar4 = pvVar1;
  pvVar5 = *(void **)(this + 8);
  if (*(void **)(this + 8) != pvVar1) {
    do {
      ozflite_metadata::~ozflite_metadata((ozflite_metadata *)((long)pvVar5 + -0xc0));
      pvVar4 = *(void **)((long)pvVar5 + -0xe0);
      if (pvVar4 != (void *)0x0) {
        pvVar2 = *(void **)((long)pvVar5 + -0xd8);
        pvVar3 = pvVar4;
        if (*(void **)((long)pvVar5 + -0xd8) != pvVar4) {
          do {
            pvVar3 = (void *)((long)pvVar2 + -0x20);
            if ((*(byte *)((long)pvVar2 + -0x18) & 1) != 0) {
              operator_delete(*(void **)((long)pvVar2 + -8));
            }
            pvVar2 = pvVar3;
          } while (pvVar3 != pvVar4);
          pvVar3 = *(void **)((long)pvVar5 + -0xe0);
        }
        *(void **)((long)pvVar5 + -0xd8) = pvVar4;
        operator_delete(pvVar3);
      }
      pvVar4 = (void *)((long)pvVar5 + -0x288);
      aircraft_metadata::~aircraft_metadata((aircraft_metadata *)((long)pvVar5 + -0x250));
      if ((*(byte *)((long)pvVar5 + -0x268) & 1) != 0) {
        operator_delete(*(void **)((long)pvVar5 + -600));
      }
      pvVar5 = pvVar4;
    } while (pvVar4 != pvVar1);
    pvVar4 = *(void **)this;
  }
  *(void **)(this + 8) = pvVar1;
  operator_delete(pvVar4);
  return;
}


// 00049b50  analytics_flight::analytics_flight

/* analytics_flight::analytics_flight(analytics_flight&&) */

void __thiscall analytics_flight::analytics_flight(analytics_flight *this,analytics_flight *param_1)

{
  long lVar1;
  long lVar2;
  undefined8 uVar3;
  undefined8 uVar4;
  undefined8 uVar5;
  
  uVar3 = *(undefined8 *)param_1;
  uVar4 = *(undefined8 *)(param_1 + 8);
  uVar5 = *(undefined8 *)(param_1 + 0x18);
  *(undefined8 *)(this + 0x10) = *(undefined8 *)(param_1 + 0x10);
  *(undefined8 *)(this + 0x18) = uVar5;
  *(undefined8 *)this = uVar3;
  *(undefined8 *)(this + 8) = uVar4;
  *(undefined8 *)(this + 0x30) = *(undefined8 *)(param_1 + 0x30);
  uVar3 = *(undefined8 *)(param_1 + 0x28);
  *(undefined8 *)(this + 0x20) = *(undefined8 *)(param_1 + 0x20);
  *(undefined8 *)(this + 0x28) = uVar3;
  *(undefined8 *)(param_1 + 0x20) = 0;
  *(undefined8 *)(param_1 + 0x28) = 0;
  *(undefined8 *)(param_1 + 0x30) = 0;
  *(undefined8 *)(this + 0x48) = *(undefined8 *)(param_1 + 0x48);
  uVar3 = *(undefined8 *)(param_1 + 0x40);
  *(undefined8 *)(this + 0x38) = *(undefined8 *)(param_1 + 0x38);
  *(undefined8 *)(this + 0x40) = uVar3;
  *(undefined8 *)(param_1 + 0x38) = 0;
  *(undefined8 *)(param_1 + 0x40) = 0;
  *(undefined8 *)(param_1 + 0x48) = 0;
  *(undefined8 *)(this + 0x60) = *(undefined8 *)(param_1 + 0x60);
  uVar3 = *(undefined8 *)(param_1 + 0x58);
  *(undefined8 *)(this + 0x50) = *(undefined8 *)(param_1 + 0x50);
  *(undefined8 *)(this + 0x58) = uVar3;
  *(undefined8 *)(param_1 + 0x50) = 0;
  *(undefined8 *)(param_1 + 0x58) = 0;
  *(undefined8 *)(param_1 + 0x60) = 0;
  *(undefined8 *)(this + 0x78) = *(undefined8 *)(param_1 + 0x78);
  uVar3 = *(undefined8 *)(param_1 + 0x70);
  *(undefined8 *)(this + 0x68) = *(undefined8 *)(param_1 + 0x68);
  *(undefined8 *)(this + 0x70) = uVar3;
  *(undefined8 *)(param_1 + 0x68) = 0;
  *(undefined8 *)(param_1 + 0x70) = 0;
  *(undefined8 *)(param_1 + 0x78) = 0;
  *(undefined8 *)(this + 0x90) = *(undefined8 *)(param_1 + 0x90);
  uVar3 = *(undefined8 *)(param_1 + 0x88);
  *(undefined8 *)(this + 0x80) = *(undefined8 *)(param_1 + 0x80);
  *(undefined8 *)(this + 0x88) = uVar3;
  *(undefined8 *)(param_1 + 0x80) = 0;
  *(undefined8 *)(param_1 + 0x88) = 0;
  *(undefined8 *)(param_1 + 0x90) = 0;
  *(undefined8 *)(this + 0xa8) = *(undefined8 *)(param_1 + 0xa8);
  uVar3 = *(undefined8 *)(param_1 + 0xa0);
  *(undefined8 *)(this + 0x98) = *(undefined8 *)(param_1 + 0x98);
  *(undefined8 *)(this + 0xa0) = uVar3;
  *(undefined8 *)(param_1 + 0x98) = 0;
  *(undefined8 *)(param_1 + 0xa0) = 0;
  *(undefined8 *)(param_1 + 0xa8) = 0;
  this[0xb4] = param_1[0xb4];
  *(undefined4 *)(this + 0xb0) = *(undefined4 *)(param_1 + 0xb0);
  uVar3 = *(undefined8 *)(param_1 + 0xc0);
  *(undefined8 *)(this + 0xb8) = *(undefined8 *)(param_1 + 0xb8);
  *(undefined8 *)(this + 0xc0) = uVar3;
  *(undefined8 *)(this + 200) = *(undefined8 *)(param_1 + 200);
  *(undefined8 *)(param_1 + 0xb8) = 0;
  *(undefined8 *)(param_1 + 0xc0) = 0;
  *(undefined8 *)(param_1 + 200) = 0;
  *(undefined8 *)(this + 0xe0) = *(undefined8 *)(param_1 + 0xe0);
  uVar3 = *(undefined8 *)(param_1 + 0xd8);
  *(undefined8 *)(this + 0xd0) = *(undefined8 *)(param_1 + 0xd0);
  *(undefined8 *)(this + 0xd8) = uVar3;
  *(undefined8 *)(param_1 + 0xd0) = 0;
  *(undefined8 *)(param_1 + 0xd8) = 0;
  *(undefined8 *)(param_1 + 0xe0) = 0;
  *(undefined8 *)(this + 0xf8) = *(undefined8 *)(param_1 + 0xf8);
  uVar3 = *(undefined8 *)(param_1 + 0xf0);
  *(undefined8 *)(this + 0xe8) = *(undefined8 *)(param_1 + 0xe8);
  *(undefined8 *)(this + 0xf0) = uVar3;
  *(undefined8 *)(param_1 + 0xe8) = 0;
  *(undefined8 *)(param_1 + 0xf0) = 0;
  *(undefined8 *)(param_1 + 0xf8) = 0;
  *(undefined8 *)(this + 0x110) = *(undefined8 *)(param_1 + 0x110);
  uVar3 = *(undefined8 *)(param_1 + 0x108);
  *(undefined8 *)(this + 0x100) = *(undefined8 *)(param_1 + 0x100);
  *(undefined8 *)(this + 0x108) = uVar3;
  *(undefined8 *)(param_1 + 0x100) = 0;
  *(undefined8 *)(param_1 + 0x108) = 0;
  *(undefined8 *)(param_1 + 0x110) = 0;
  this[0x11c] = param_1[0x11c];
  *(undefined4 *)(this + 0x118) = *(undefined4 *)(param_1 + 0x118);
  *(undefined8 *)(this + 0x120) = 0;
  *(undefined8 *)(this + 0x128) = 0;
  *(undefined8 *)(this + 0x130) = 0;
  uVar3 = *(undefined8 *)(param_1 + 0x128);
  *(undefined8 *)(this + 0x120) = *(undefined8 *)(param_1 + 0x120);
  *(undefined8 *)(this + 0x128) = uVar3;
  *(undefined8 *)(this + 0x130) = *(undefined8 *)(param_1 + 0x130);
  *(undefined8 *)(param_1 + 0x120) = 0;
  *(undefined8 *)(param_1 + 0x128) = 0;
  *(undefined8 *)(param_1 + 0x130) = 0;
  *(undefined8 *)(this + 0x138) = 0;
  *(undefined8 *)(this + 0x140) = 0;
  *(undefined8 *)(this + 0x148) = 0;
  uVar3 = *(undefined8 *)(param_1 + 0x140);
  *(undefined8 *)(this + 0x138) = *(undefined8 *)(param_1 + 0x138);
  *(undefined8 *)(this + 0x140) = uVar3;
  *(undefined8 *)(this + 0x148) = *(undefined8 *)(param_1 + 0x148);
  *(undefined8 *)(param_1 + 0x138) = 0;
  *(undefined8 *)(param_1 + 0x140) = 0;
  *(undefined8 *)(param_1 + 0x148) = 0;
  *(undefined8 *)(this + 0x150) = *(undefined8 *)(param_1 + 0x150);
  *(undefined8 *)(this + 0x158) = *(undefined8 *)(param_1 + 0x158);
  *(undefined8 *)(this + 0x160) = *(undefined8 *)(param_1 + 0x160);
  *(undefined8 *)(param_1 + 0x150) = 0;
  *(undefined8 *)(param_1 + 0x158) = 0;
  *(undefined8 *)(param_1 + 0x160) = 0;
  *(undefined8 *)(this + 0x168) = *(undefined8 *)(param_1 + 0x168);
  lVar1 = *(long *)(param_1 + 0x170);
  *(long *)(this + 0x170) = lVar1;
  lVar2 = *(long *)(param_1 + 0x178);
  *(long *)(this + 0x178) = lVar2;
  if (lVar2 == 0) {
    *(analytics_flight **)(this + 0x168) = this + 0x170;
  }
  else {
    *(analytics_flight **)(lVar1 + 0x10) = this + 0x170;
    *(analytics_flight **)(param_1 + 0x168) = param_1 + 0x170;
    *(undefined8 *)(param_1 + 0x170) = 0;
    *(undefined8 *)(param_1 + 0x178) = 0;
  }
  this[0x184] = param_1[0x184];
  *(undefined4 *)(this + 0x180) = *(undefined4 *)(param_1 + 0x180);
  uVar3 = *(undefined8 *)(param_1 + 400);
  uVar4 = *(undefined8 *)(param_1 + 0x194);
  uVar5 = *(undefined8 *)(param_1 + 0x19c);
  *(undefined8 *)(this + 0x188) = *(undefined8 *)(param_1 + 0x188);
  *(undefined8 *)(this + 400) = uVar3;
  *(undefined8 *)(this + 0x194) = uVar4;
  *(undefined8 *)(this + 0x19c) = uVar5;
  *(undefined8 *)(this + 0x1a8) = 0;
  *(undefined8 *)(this + 0x1b0) = 0;
  *(undefined8 *)(this + 0x1b8) = 0;
  uVar3 = *(undefined8 *)(param_1 + 0x1b0);
  *(undefined8 *)(this + 0x1a8) = *(undefined8 *)(param_1 + 0x1a8);
  *(undefined8 *)(this + 0x1b0) = uVar3;
  *(undefined8 *)(this + 0x1b8) = *(undefined8 *)(param_1 + 0x1b8);
  *(undefined8 *)(param_1 + 0x1a8) = 0;
  *(undefined8 *)(param_1 + 0x1b0) = 0;
  *(undefined8 *)(param_1 + 0x1b8) = 0;
  *(undefined8 *)(this + 0x1c0) = *(undefined8 *)(param_1 + 0x1c0);
  *(undefined4 *)(this + 0x1c8) = *(undefined4 *)(param_1 + 0x1c8);
  *(undefined8 *)(this + 0x1e0) = *(undefined8 *)(param_1 + 0x1e0);
  uVar3 = *(undefined8 *)(param_1 + 0x1d8);
  *(undefined8 *)(this + 0x1d0) = *(undefined8 *)(param_1 + 0x1d0);
  *(undefined8 *)(this + 0x1d8) = uVar3;
  *(undefined8 *)(param_1 + 0x1d0) = 0;
  *(undefined8 *)(param_1 + 0x1d8) = 0;
  *(undefined8 *)(param_1 + 0x1e0) = 0;
  *(undefined8 *)(this + 0x1f8) = *(undefined8 *)(param_1 + 0x1f8);
  uVar3 = *(undefined8 *)(param_1 + 0x1f0);
  *(undefined8 *)(this + 0x1e8) = *(undefined8 *)(param_1 + 0x1e8);
  *(undefined8 *)(this + 0x1f0) = uVar3;
  *(undefined8 *)(param_1 + 0x1e8) = 0;
  *(undefined8 *)(param_1 + 0x1f0) = 0;
  *(undefined8 *)(param_1 + 0x1f8) = 0;
  *(undefined8 *)(this + 0x210) = *(undefined8 *)(param_1 + 0x210);
  uVar3 = *(undefined8 *)(param_1 + 0x208);
  *(undefined8 *)(this + 0x200) = *(undefined8 *)(param_1 + 0x200);
  *(undefined8 *)(this + 0x208) = uVar3;
  *(undefined8 *)(param_1 + 0x200) = 0;
  *(undefined8 *)(param_1 + 0x208) = 0;
  *(undefined8 *)(param_1 + 0x210) = 0;
  *(undefined8 *)(this + 0x228) = *(undefined8 *)(param_1 + 0x228);
  uVar3 = *(undefined8 *)(param_1 + 0x220);
  *(undefined8 *)(this + 0x218) = *(undefined8 *)(param_1 + 0x218);
  *(undefined8 *)(this + 0x220) = uVar3;
  *(undefined8 *)(param_1 + 0x218) = 0;
  *(undefined8 *)(param_1 + 0x220) = 0;
  *(undefined8 *)(param_1 + 0x228) = 0;
  *(undefined8 *)(this + 0x240) = *(undefined8 *)(param_1 + 0x240);
  uVar3 = *(undefined8 *)(param_1 + 0x238);
  *(undefined8 *)(this + 0x230) = *(undefined8 *)(param_1 + 0x230);
  *(undefined8 *)(this + 0x238) = uVar3;
  *(undefined8 *)(param_1 + 0x230) = 0;
  *(undefined8 *)(param_1 + 0x238) = 0;
  *(undefined8 *)(param_1 + 0x240) = 0;
  *(undefined8 *)(this + 600) = *(undefined8 *)(param_1 + 600);
  uVar3 = *(undefined8 *)(param_1 + 0x250);
  *(undefined8 *)(this + 0x248) = *(undefined8 *)(param_1 + 0x248);
  *(undefined8 *)(this + 0x250) = uVar3;
  *(undefined8 *)(param_1 + 0x248) = 0;
  *(undefined8 *)(param_1 + 0x250) = 0;
  *(undefined8 *)(param_1 + 600) = 0;
  *(undefined8 *)(this + 0x270) = *(undefined8 *)(param_1 + 0x270);
  uVar3 = *(undefined8 *)(param_1 + 0x268);
  *(undefined8 *)(this + 0x260) = *(undefined8 *)(param_1 + 0x260);
  *(undefined8 *)(this + 0x268) = uVar3;
  *(undefined8 *)(param_1 + 0x260) = 0;
  *(undefined8 *)(param_1 + 0x268) = 0;
  *(undefined8 *)(param_1 + 0x270) = 0;
  uVar3 = *(undefined8 *)(param_1 + 0x280);
  *(undefined8 *)(this + 0x278) = *(undefined8 *)(param_1 + 0x278);
  *(undefined8 *)(this + 0x280) = uVar3;
  return;
}


// 0004a020  std::__vector_base<analytics_flight,std::allocator<analytics_flight>>::__throw_length_error

/* std::__vector_base<analytics_flight, std::allocator<analytics_flight> >::__throw_length_error()
   const */

void std::__vector_base<analytics_flight,std::allocator<analytics_flight>>::__throw_length_error
               (void)

{
                    /* WARNING: Subroutine does not return */
  std::__vector_base_common<true>::__throw_length_error();
}


// 0004a030  std::__split_buffer<analytics_flight,std::allocator<analytics_flight>&>::~__split_buffer

/* std::__split_buffer<analytics_flight, std::allocator<analytics_flight>&>::~__split_buffer() */

void __thiscall
std::__split_buffer<analytics_flight,std::allocator<analytics_flight>&>::~__split_buffer
          (__split_buffer<analytics_flight,std::allocator<analytics_flight>&> *this)

{
  long lVar1;
  void *pvVar2;
  void *pvVar3;
  void *pvVar4;
  long lVar5;
  
  lVar1 = *(long *)(this + 8);
  lVar5 = *(long *)(this + 0x10);
  while (lVar5 != lVar1) {
    *(long *)(this + 0x10) = lVar5 + -0x288;
    ozflite_metadata::~ozflite_metadata((ozflite_metadata *)(lVar5 + -0xc0));
    pvVar2 = *(void **)(lVar5 + -0xe0);
    if (pvVar2 != (void *)0x0) {
      pvVar3 = *(void **)(lVar5 + -0xd8);
      pvVar4 = pvVar2;
      if (*(void **)(lVar5 + -0xd8) != pvVar2) {
        do {
          pvVar4 = (void *)((long)pvVar3 + -0x20);
          if ((*(byte *)((long)pvVar3 + -0x18) & 1) != 0) {
            operator_delete(*(void **)((long)pvVar3 + -8));
          }
          pvVar3 = pvVar4;
        } while (pvVar4 != pvVar2);
        pvVar4 = *(void **)(lVar5 + -0xe0);
      }
      *(void **)(lVar5 + -0xd8) = pvVar2;
      operator_delete(pvVar4);
    }
    aircraft_metadata::~aircraft_metadata((aircraft_metadata *)(lVar5 + -0x250));
    if ((*(byte *)(lVar5 + -0x268) & 1) != 0) {
      operator_delete(*(void **)(lVar5 + -600));
    }
    lVar5 = *(long *)(this + 0x10);
  }
  if (*(void **)this == (void *)0x0) {
    return;
  }
  operator_delete(*(void **)this);
  return;
}


// 0004a130  std::__vector_base<flight_event,std::allocator<flight_event>>::__throw_length_error

/* std::__vector_base<flight_event, std::allocator<flight_event> >::__throw_length_error() const */

void std::__vector_base<flight_event,std::allocator<flight_event>>::__throw_length_error(void)

{
                    /* WARNING: Subroutine does not return */
  std::__vector_base_common<true>::__throw_length_error();
}


// 0005b0f0  cli_start_new_flight

/* cli_start_new_flight(CLI_output_pipe*, std::vector<std::string, std::allocator<std::string > >
   const&) */

void cli_start_new_flight(CLI_output_pipe *param_1,vector *param_2)

{
  cli_init_flight_impl(param_1,param_2,false);
  return;
}


// 0005b100  cli_update_current_flight

/* cli_update_current_flight(CLI_output_pipe*, std::vector<std::string, std::allocator<std::string >
   > const&) */

void cli_update_current_flight(CLI_output_pipe *param_1,vector *param_2)

{
  cli_init_flight_impl(param_1,param_2,true);
  return;
}


// 00064480  flight_spec::flight_spec

/* flight_spec::flight_spec(flight_spec const&) */

void __thiscall flight_spec::flight_spec(flight_spec *this,flight_spec *param_1)

{
  __tree<std::__value_type<int,std::string>,std::__map_value_compare<int,std::__value_type<int,std::string>,std::less<int>,true>,std::allocator<std::__value_type<int,std::string>>>
  *p_Var1;
  flight_spec *pfVar2;
  flight_spec *pfVar3;
  flight_spec *pfVar4;
  code *pcVar5;
  void *pvVar6;
  flight_spec *pfVar7;
  ulong uVar8;
  undefined1 local_48 [16];
  flight_spec *local_38;
  
  *this = (flight_spec)0x0;
  this[0x60] = (flight_spec)0x0;
  local_38 = this;
  if (param_1[0x60] != (flight_spec)0x0) {
    *this = (flight_spec)0x0;
    *(undefined4 *)(this + 0x58) = 0xffffffff;
    if ((ulong)*(uint *)(param_1 + 0x58) != 0xffffffff) {
      (*(code *)(&
                PTR___dispatch<std::__variant_detail::__ctor<std::__variant_detail::__traits<runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>>::__generic_construct<std::__variant_detail::__copy_constructor<std::__variant_detail::__traits<runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>,(std::__variant_detail::_Trait)1>const&>(std::__variant_detail::__ctor<std::__variant_detail::__traits<runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>>&,std::__variant_detail::__copy_constructor<std::__variant_detail::__traits<runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>,(std::__variant_detail::_Trait)1>const&)::_lambda(auto:1&,auto:2&&)_1_&&,std::__variant_detail::__base<(std::__variant_detail::_Trait)1,runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>&,std::__variant_detail::__base<(std::__variant_detail::_Trait)1,runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>const&>_02ac5d08
                )[*(uint *)(param_1 + 0x58)])(local_48,this,param_1);
      *(undefined4 *)(this + 0x58) = *(undefined4 *)(param_1 + 0x58);
    }
    this[0x60] = (flight_spec)0x1;
  }
  std::optional<aircraft_spec>::optional
            ((optional<aircraft_spec> *)(this + 0x68),(optional *)(param_1 + 0x68));
  this[0xa0] = (flight_spec)0x0;
  this[0xf0] = (flight_spec)0x0;
  if (param_1[0xf0] != (flight_spec)0x0) {
    this[0xa0] = param_1[0xa0];
    *(undefined8 *)(this + 0xa8) = 0;
    *(undefined8 *)(this + 0xb0) = 0;
    *(undefined8 *)(this + 0xb8) = 0;
    uVar8 = *(long *)(param_1 + 0xb0) - *(long *)(param_1 + 0xa8);
    if (uVar8 != 0) {
      if (0x1555555555555555 < (ulong)(((long)uVar8 >> 2) * -0x5555555555555555)) {
        std::__vector_base<failure_spec::veh_failure,std::allocator<failure_spec::veh_failure>>::
        __throw_length_error();
                    /* WARNING: Does not return */
        pcVar5 = (code *)invalidInstructionException();
        (*pcVar5)();
      }
      pvVar6 = operator_new(uVar8);
      *(void **)(local_38 + 0xb0) = pvVar6;
      *(void **)(local_38 + 0xa8) = pvVar6;
      *(void **)(local_38 + 0xb8) = (void *)((long)pvVar6 + ((long)uVar8 >> 2) * 4);
      uVar8 = *(long *)(param_1 + 0xb0) - (long)*(void **)(param_1 + 0xa8);
      if (0 < (long)uVar8) {
        _memcpy(pvVar6,*(void **)(param_1 + 0xa8),uVar8);
        pvVar6 = (void *)((long)pvVar6 + (uVar8 / 0xc) * 0xc);
      }
      *(void **)(local_38 + 0xb0) = pvVar6;
      this = local_38;
    }
    std::
    unordered_map<vec_nav_struct*,bool,std::hash<vec_nav_struct*>,std::equal_to<vec_nav_struct*>,std::allocator<std::pair<vec_nav_struct*const,bool>>>
    ::unordered_map((unordered_map<vec_nav_struct*,bool,std::hash<vec_nav_struct*>,std::equal_to<vec_nav_struct*>,std::allocator<std::pair<vec_nav_struct*const,bool>>>
                     *)(this + 0xc0),(unordered_map *)(param_1 + 0xc0));
    *(undefined8 *)(this + 0xe8) = *(undefined8 *)(param_1 + 0xe8);
    this[0xf0] = (flight_spec)0x1;
  }
  this[0xf8] = (flight_spec)0x0;
  this[0x130] = (flight_spec)0x0;
  if (param_1[0x130] != (flight_spec)0x0) {
    *(undefined4 *)(this + 0xf8) = *(undefined4 *)(param_1 + 0xf8);
    std::string::string((string *)(this + 0x100),(string *)(param_1 + 0x100));
    std::string::string((string *)(this + 0x118),(string *)(param_1 + 0x118));
    this[0x130] = (flight_spec)0x1;
  }
  this[0x138] = (flight_spec)0x0;
  this[0x170] = (flight_spec)0x0;
  if (param_1[0x170] != (flight_spec)0x0) {
    std::string::string((string *)(this + 0x138),(string *)(param_1 + 0x138));
    std::string::string((string *)(this + 0x150),(string *)(param_1 + 0x150));
    *(undefined4 *)(this + 0x168) = *(undefined4 *)(param_1 + 0x168);
    this[0x170] = (flight_spec)0x1;
  }
  p_Var1 = (__tree<std::__value_type<int,std::string>,std::__map_value_compare<int,std::__value_type<int,std::string>,std::less<int>,true>,std::allocator<std::__value_type<int,std::string>>>
            *)(this + 0x178);
  this[0x178] = (flight_spec)0x0;
  this[400] = (flight_spec)0x0;
  if (param_1[400] != (flight_spec)0x0) {
    pfVar2 = this + 0x180;
    *(undefined8 *)(this + 0x180) = 0;
    *(undefined8 *)(this + 0x188) = 0;
    *(flight_spec **)(this + 0x178) = pfVar2;
    pfVar7 = *(flight_spec **)(param_1 + 0x178);
    this = local_38;
    while (pfVar4 = pfVar7, local_38 = this, pfVar4 != param_1 + 0x180) {
      std::
      __tree<std::__value_type<int,std::string>,std::__map_value_compare<int,std::__value_type<int,std::string>,std::less<int>,true>,std::allocator<std::__value_type<int,std::string>>>
      ::__emplace_hint_unique_key_args<int,std::pair<int_const,std::string>const&>
                (p_Var1,pfVar2,pfVar4 + 0x20);
      pfVar3 = *(flight_spec **)(pfVar4 + 8);
      this = local_38;
      if (*(flight_spec **)(pfVar4 + 8) == (flight_spec *)0x0) {
        pfVar7 = *(flight_spec **)(pfVar4 + 0x10);
        if (*(flight_spec **)*(flight_spec **)(pfVar4 + 0x10) != pfVar4) {
          do {
            pfVar4 = *(flight_spec **)(pfVar4 + 0x10);
            pfVar7 = *(flight_spec **)(pfVar4 + 0x10);
          } while (*(flight_spec **)*(flight_spec **)(pfVar4 + 0x10) != pfVar4);
        }
      }
      else {
        do {
          pfVar7 = pfVar3;
          pfVar3 = *(flight_spec **)pfVar7;
        } while (pfVar3 != (flight_spec *)0x0);
      }
    }
    this[400] = (flight_spec)0x1;
  }
  this[0x198] = (flight_spec)0x0;
  this[0x270] = (flight_spec)0x0;
  if (param_1[0x270] != (flight_spec)0x0) {
    weight_spec::weight_spec((weight_spec *)(this + 0x198),(weight_spec *)(param_1 + 0x198));
    this[0x270] = (flight_spec)0x1;
  }
  _memcpy(this + 0x278,param_1 + 0x278,0x1d1);
  this[0x450] = (flight_spec)0x0;
  this[0x468] = (flight_spec)0x0;
  if (param_1[0x468] != (flight_spec)0x0) {
    std::vector<ai_spec,std::allocator<ai_spec>>::vector
              ((vector<ai_spec,std::allocator<ai_spec>> *)(this + 0x450),(vector *)(param_1 + 0x450)
              );
    this[0x468] = (flight_spec)0x1;
  }
  this[0x472] = param_1[0x472];
  *(undefined2 *)(this + 0x470) = *(undefined2 *)(param_1 + 0x470);
  return;
}


// 00065a10  ATCAircraftFlightInfo::ATCAircraftFlightInfo

/* ATCAircraftFlightInfo::ATCAircraftFlightInfo(ATCAircraftFlightInfo const&) */

void __thiscall
ATCAircraftFlightInfo::ATCAircraftFlightInfo
          (ATCAircraftFlightInfo *this,ATCAircraftFlightInfo *param_1)

{
  std::string::string((string *)this,(string *)param_1);
  std::string::string((string *)(this + 0x18),(string *)(param_1 + 0x18));
  std::string::string((string *)(this + 0x30),(string *)(param_1 + 0x30));
  *(undefined4 *)(this + 0x48) = *(undefined4 *)(param_1 + 0x48);
  std::string::string((string *)(this + 0x50),(string *)(param_1 + 0x50));
  return;
}


// 00065ae0  cli_init_flight_impl

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* cli_init_flight_impl(CLI_output_pipe*, std::vector<std::string, std::allocator<std::string > >
   const&, bool) */

void cli_init_flight_impl(CLI_output_pipe *param_1,vector *param_2,bool param_3)

{
  string *psVar1;
  long lVar2;
  code *pcVar3;
  undefined8 uVar4;
  int iVar5;
  uint uVar6;
  size_t sVar7;
  void *pvVar8;
  char *pcVar9;
  ulong uVar10;
  undefined1 *puVar11;
  ulong uVar12;
  uint uVar13;
  char *pcVar14;
  ulong uVar15;
  byte bVar16;
  long lVar17;
  ulong local_88;
  undefined8 uStack_80;
  char *local_78;
  char *local_68;
  char *pcStack_60;
  char *local_58;
  vector *local_50;
  undefined8 local_48;
  size_t local_40;
  void *local_38;
  
  lVar2 = *(long *)param_2;
  psVar1 = (string *)(lVar2 + 0x48);
  local_68 = (char *)0x0;
  pcStack_60 = (char *)0x0;
  local_58 = (char *)0x0;
  iVar5 = FILE_disk_to_buffer_uncached(psVar1,(vector *)&local_68,(string *)0x0,(int *)0x0,0);
  pcVar14 = local_68;
  if (iVar5 == 0) {
    if (pcStack_60 < local_58) {
      *pcStack_60 = '\0';
      pcStack_60 = pcStack_60 + 1;
    }
    else {
      sVar7 = (long)pcStack_60 - (long)local_68;
      uVar15 = sVar7 + 1;
      if ((long)uVar15 < 0) {
        std::__vector_base<unsigned_char,std::allocator<unsigned_char>>::__throw_length_error();
                    /* WARNING: Does not return */
        pcVar3 = (code *)invalidInstructionException();
        (*pcVar3)();
      }
      uVar10 = ((long)local_58 - (long)local_68) * 2;
      if (uVar10 < uVar15) {
        uVar10 = uVar15;
      }
      uVar15 = 0x7fffffffffffffff;
      if ((ulong)((long)local_58 - (long)local_68) < 0x3fffffffffffffff) {
        uVar15 = uVar10;
      }
      if (uVar15 == 0) {
        pcVar9 = (char *)0x0;
        local_50 = param_2;
      }
      else {
        local_50 = param_2;
        pcVar9 = operator_new(uVar15);
      }
      pcVar9[sVar7] = '\0';
      if (0 < (long)sVar7) {
        _memcpy(pcVar9,pcVar14,sVar7);
      }
      param_2 = local_50;
      local_68 = pcVar9;
      pcStack_60 = pcVar9 + sVar7 + 1;
      local_58 = pcVar9 + uVar15;
      if (pcVar14 != (char *)0x0) {
        operator_delete(pcVar14);
      }
    }
    lVar17 = *(long *)param_2;
    uVar13 = 0;
    if (*(long *)(param_2 + 8) - lVar17 == 0x78) {
      uVar10 = (ulong)(*(byte *)(lVar17 + 0x60) >> 1);
      bVar16 = *(byte *)(lVar17 + 0x60) & 1;
      uVar15 = *(ulong *)(lVar17 + 0x68);
      uVar12 = uVar15;
      if (bVar16 == 0) {
        uVar12 = uVar10;
      }
      if (uVar12 == 0x11) {
        std::string::compare(lVar17 + 0x60,0,(char *)0xffffffffffffffff,0x27876ff);
        lVar17 = *(long *)param_2;
        uVar15 = *(ulong *)(lVar17 + 0x68);
        bVar16 = *(byte *)(lVar17 + 0x60) & 1;
        uVar10 = (ulong)(*(byte *)(lVar17 + 0x60) >> 1);
      }
      uVar12 = uVar15;
      if (bVar16 == 0) {
        uVar12 = uVar10;
      }
      uVar13 = 0;
      if (uVar12 == 0x11) {
        iVar5 = std::string::compare(lVar17 + 0x60,0,(char *)0xffffffffffffffff,0x2787711);
        uVar13 = (uint)(iVar5 == 0);
        lVar17 = *(long *)param_2;
        uVar15 = *(ulong *)(lVar17 + 0x68);
        bVar16 = *(byte *)(lVar17 + 0x60) & 1;
        uVar10 = (ulong)(*(byte *)(lVar17 + 0x60) >> 1);
      }
      uVar12 = uVar15;
      if (bVar16 == 0) {
        uVar12 = uVar10;
      }
      if (uVar12 == 0x19) {
        iVar5 = std::string::compare(lVar17 + 0x60,0,(char *)0xffffffffffffffff,0x2787723);
        if (iVar5 == 0) {
          uVar13 = 2;
        }
        lVar17 = *(long *)param_2;
        uVar15 = *(ulong *)(lVar17 + 0x68);
        bVar16 = *(byte *)(lVar17 + 0x60) & 1;
        uVar10 = (ulong)(*(byte *)(lVar17 + 0x60) >> 1);
      }
      uVar12 = uVar15;
      if (bVar16 == 0) {
        uVar12 = uVar10;
      }
      if (uVar12 == 0x17) {
        iVar5 = std::string::compare(lVar17 + 0x60,0,(char *)0xffffffffffffffff,0x278773d);
        if (iVar5 == 0) {
          uVar13 = 3;
        }
        lVar17 = *(long *)param_2;
        uVar15 = *(ulong *)(lVar17 + 0x68);
        bVar16 = *(byte *)(lVar17 + 0x60) & 1;
        uVar10 = (ulong)(*(byte *)(lVar17 + 0x60) >> 1);
      }
      uVar12 = uVar15;
      if (bVar16 == 0) {
        uVar12 = uVar10;
      }
      if (uVar12 == 0x18) {
        iVar5 = std::string::compare(lVar17 + 0x60,0,(char *)0xffffffffffffffff,0x2787755);
        if (iVar5 == 0) {
          uVar13 = 4;
        }
        lVar17 = *(long *)param_2;
        uVar15 = *(ulong *)(lVar17 + 0x68);
        bVar16 = *(byte *)(lVar17 + 0x60) & 1;
        uVar10 = (ulong)(*(byte *)(lVar17 + 0x60) >> 1);
      }
      uVar12 = uVar15;
      if (bVar16 == 0) {
        uVar12 = uVar10;
      }
      if (uVar12 == 0x15) {
        iVar5 = std::string::compare(lVar17 + 0x60,0,(char *)0xffffffffffffffff,0x278776e);
        if (iVar5 == 0) {
          uVar13 = 5;
        }
        lVar17 = *(long *)param_2;
        uVar15 = *(ulong *)(lVar17 + 0x68);
        bVar16 = *(byte *)(lVar17 + 0x60) & 1;
        uVar10 = (ulong)(*(byte *)(lVar17 + 0x60) >> 1);
      }
      if (bVar16 != 0) {
        uVar10 = uVar15;
      }
      if ((uVar10 == 0x17) &&
         (iVar5 = std::string::compare(lVar17 + 0x60,0,(char *)0xffffffffffffffff,0x2787784),
         iVar5 == 0)) {
        uVar13 = 6;
      }
    }
    if ((cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)
         ::error_msg == '\0') &&
       (iVar5 = ___cxa_guard_acquire
                          (&cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)
                            ::error_msg), iVar5 != 0)) {
      _error_msg = 0;
      _DAT_02db6b48 = 0;
      DAT_02db6b50 = (undefined1 *)0x0;
      ___cxa_atexit(PTR__string_02ac0108,
                    &cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)
                     ::error_msg,0x10000);
      ___cxa_guard_release
                (&cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)
                  ::error_msg);
    }
    if ((_error_msg & 1) == 0) {
      _error_msg = _error_msg & 0xffffffffffff0000;
      if (param_3) goto LAB_00065f65;
LAB_00065f35:
      uVar6 = XPInitFlight(local_68,cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)
                                    ::$_30::__invoke);
    }
    else {
      *DAT_02db6b50 = 0;
      _DAT_02db6b48 = 0;
      if (!param_3) goto LAB_00065f35;
LAB_00065f65:
      uVar6 = XPUpdateFlight(local_68,cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)
                                      ::$_29::__invoke);
    }
    if (uVar6 == uVar13) goto LAB_0006606d;
    puVar11 = DAT_02db6b50;
    if ((_error_msg & 1) == 0) {
      puVar11 = &DAT_02db6b41;
    }
    stl_printf((char *)&local_88,
               "XPInitFlight() call returned unexpected result. Expected: %d. Error message: %s",
               (ulong)uVar6,puVar11);
    if (((byte)*psVar1 & 1) == 0) {
      pcVar14 = (char *)(lVar2 + 0x49);
    }
    else {
      pcVar14 = *(char **)(lVar2 + 0x58);
    }
    sVar7 = _strlen(pcVar14);
    if (0xffffffffffffffef < sVar7) {
                    /* WARNING: Subroutine does not return */
      std::string::__throw_length_error();
    }
    if (sVar7 < 0x17) {
      local_48 = CONCAT71(local_48._1_7_,(char)sVar7 * '\x02');
      pvVar8 = (void *)((long)&local_48 + 1);
      if (sVar7 != 0) goto LAB_00066023;
    }
    else {
      uVar15 = sVar7 + 0x10 & 0xfffffffffffffff0;
      local_50 = param_2;
      pvVar8 = operator_new(uVar15);
      local_48 = uVar15 | 1;
      param_2 = local_50;
      local_40 = sVar7;
      local_38 = pvVar8;
LAB_00066023:
      _memcpy(pvVar8,pcVar14,sVar7);
    }
    *(undefined1 *)((long)pvVar8 + sVar7) = 0;
    CLI_report_test_result(param_1,param_2,(string *)&local_88,(string *)&local_48,false,0.0);
  }
  else {
    local_78 = operator_new(0x30);
    uVar4 = s_Failed_to_read_json_file_from_di_027876dc._24_8_;
    local_88 = _DAT_025203d0;
    uStack_80 = _UNK_025203d8;
    *(undefined8 *)(local_78 + 0x10) = s_Failed_to_read_json_file_from_di_027876dc._16_8_;
    *(undefined8 *)(local_78 + 0x18) = uVar4;
    uVar4 = s_Failed_to_read_json_file_from_di_027876dc._8_8_;
    *(undefined8 *)local_78 = s_Failed_to_read_json_file_from_di_027876dc._0_8_;
    *(undefined8 *)(local_78 + 8) = uVar4;
    local_78[0x20] = 's';
    local_78[0x21] = 'k';
    local_78[0x22] = '\0';
    if (((byte)*psVar1 & 1) == 0) {
      pcVar14 = (char *)(lVar2 + 0x49);
    }
    else {
      pcVar14 = *(char **)(lVar2 + 0x58);
    }
    sVar7 = _strlen(pcVar14);
    if (0xffffffffffffffef < sVar7) {
                    /* WARNING: Subroutine does not return */
      std::string::__throw_length_error();
    }
    if (sVar7 < 0x17) {
      local_48 = CONCAT71(local_48._1_7_,(char)sVar7 * '\x02');
      pvVar8 = (void *)((long)&local_48 + 1);
      if (sVar7 != 0) goto LAB_00065c08;
    }
    else {
      uVar15 = sVar7 + 0x10 & 0xfffffffffffffff0;
      local_50 = param_2;
      pvVar8 = operator_new(uVar15);
      local_48 = uVar15 | 1;
      param_2 = local_50;
      local_40 = sVar7;
      local_38 = pvVar8;
LAB_00065c08:
      _memcpy(pvVar8,pcVar14,sVar7);
    }
    *(undefined1 *)((long)pvVar8 + sVar7) = 0;
    CLI_report_test_result(param_1,param_2,(string *)&local_88,(string *)&local_48,false,0.0);
  }
  if ((local_48 & 1) != 0) {
    operator_delete(local_38);
  }
  if ((local_88 & 1) != 0) {
    operator_delete(local_78);
  }
LAB_0006606d:
  if (local_68 != (char *)0x0) {
    pcStack_60 = local_68;
    operator_delete(local_68);
  }
  return;
}


// 000661d0  cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)::$_29::__invoke

/* __invoke(char const*) */

void cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)
     ::$_29::__invoke(char *param_1)

{
  std::string::assign(&error_msg);
  return;
}


// 000661f0  cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)::$_30::__invoke

/* __invoke(char const*) */

void cli_init_flight_impl(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>const&,bool)
     ::$_30::__invoke(char *param_1)

{
  std::string::assign(&error_msg);
  return;
}


// 0006e230  CLI_simple_factory<cli_wait_flight_started>::~CLI_simple_factory

/* CLI_simple_factory<cli_wait_flight_started>::~CLI_simple_factory() */

void __thiscall
CLI_simple_factory<cli_wait_flight_started>::~CLI_simple_factory
          (CLI_simple_factory<cli_wait_flight_started> *this)

{
  return;
}


// 0006e240  CLI_simple_factory<cli_wait_flight_started>::~CLI_simple_factory

/* CLI_simple_factory<cli_wait_flight_started>::~CLI_simple_factory() */

void __thiscall
CLI_simple_factory<cli_wait_flight_started>::~CLI_simple_factory
          (CLI_simple_factory<cli_wait_flight_started> *this)

{
  operator_delete(this);
  return;
}


// 0006e250  CLI_simple_factory<cli_wait_flight_started>::build

/* CLI_simple_factory<cli_wait_flight_started>::build(CLI_execution_queue&, CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&) */

CLI_execution_queue *
CLI_simple_factory<cli_wait_flight_started>::build
          (CLI_execution_queue *param_1,CLI_output_pipe *param_2,vector *param_3)

{
  cli_wait_flight_started *this;
  CLI_output_pipe *in_RCX;
  vector *in_R8;
  cli_wait_flight_started *local_30;
  
  *(undefined8 *)param_1 = 0;
  *(undefined8 *)(param_1 + 8) = 0;
  *(undefined8 *)(param_1 + 0x10) = 0;
  this = operator_new(0xd0);
  cli_wait_flight_started::cli_wait_flight_started(this,in_RCX,in_R8);
  local_30 = this;
  std::
  vector<std::unique_ptr<CLI_command,std::default_delete<CLI_command>>,std::allocator<std::unique_ptr<CLI_command,std::default_delete<CLI_command>>>>
  ::push_back((vector<std::unique_ptr<CLI_command,std::default_delete<CLI_command>>,std::allocator<std::unique_ptr<CLI_command,std::default_delete<CLI_command>>>>
               *)param_1,(unique_ptr *)&local_30);
  if (local_30 != (cli_wait_flight_started *)0x0) {
    (**(code **)(*(long *)local_30 + 8))();
  }
  return param_1;
}


// 0006e360  cli_wait_flight_started::cli_wait_flight_started

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*, std::vector<std::string,
   std::allocator<std::string > >&) */

void __thiscall
cli_wait_flight_started::cli_wait_flight_started
          (cli_wait_flight_started *this,CLI_output_pipe *param_1,vector *param_2)

{
  long lVar1;
  double dVar2;
  undefined4 uVar3;
  undefined4 uVar4;
  undefined4 uVar5;
  undefined8 uVar6;
  char *pcVar7;
  ulong local_98;
  undefined8 uStack_90;
  char *local_88;
  byte local_80;
  char local_7f [8];
  undefined5 uStack_77;
  undefined2 uStack_72;
  undefined1 uStack_70;
  undefined5 uStack_6f;
  undefined1 uStack_6a;
  undefined1 uStack_69;
  undefined **local_68 [4];
  undefined ***local_48;
  long local_38;
  
  local_38 = *(long *)PTR____stack_chk_guard_02ac0540;
  local_68[0] = &PTR____func_02ac67c0;
  local_48 = local_68;
  lVar1 = *(long *)param_2;
  if ((*(byte *)(lVar1 + 0x30) & 1) == 0) {
    pcVar7 = (char *)(lVar1 + 0x31);
  }
  else {
    pcVar7 = *(char **)(lVar1 + 0x40);
  }
  dVar2 = _strtod(pcVar7,(char **)0x0);
  local_80 = 0x2a;
  local_7f[0] = s_flight_to_get_started_02787ebb[0];
  local_7f[1] = s_flight_to_get_started_02787ebb[1];
  local_7f[2] = s_flight_to_get_started_02787ebb[2];
  local_7f[3] = s_flight_to_get_started_02787ebb[3];
  local_7f[4] = s_flight_to_get_started_02787ebb[4];
  local_7f[5] = s_flight_to_get_started_02787ebb[5];
  local_7f[6] = s_flight_to_get_started_02787ebb[6];
  local_7f[7] = s_flight_to_get_started_02787ebb[7];
  uStack_77 = (undefined5)s_flight_to_get_started_02787ebb._8_8_;
  uStack_72 = 0x7320;
  uStack_70 = 0x74;
  uStack_6f = 0x6465747261;
  uStack_6a = 0;
  local_88 = operator_new(0x20);
  uVar6 = s_no_flight_was_in_progress_02787ed1._17_8_;
  local_98 = _DAT_02520200;
  uStack_90 = _UNK_02520208;
  *(ulong *)(local_88 + 9) =
       CONCAT17(s_no_flight_was_in_progress_02787ed1[0x10],
                CONCAT43(s_no_flight_was_in_progress_02787ed1._12_4_,
                         s_no_flight_was_in_progress_02787ed1._9_3_));
  *(undefined8 *)(local_88 + 0x11) = uVar6;
  uVar5 = s_no_flight_was_in_progress_02787ed1._12_4_;
  uVar4 = s_no_flight_was_in_progress_02787ed1._8_4_;
  uVar3 = s_no_flight_was_in_progress_02787ed1._4_4_;
  *(undefined4 *)local_88 = s_no_flight_was_in_progress_02787ed1._0_4_;
  *(undefined4 *)(local_88 + 4) = uVar3;
  *(undefined4 *)(local_88 + 8) = uVar4;
  *(undefined4 *)(local_88 + 0xc) = uVar5;
  local_88[0x19] = '\0';
  cli_await_predicate::cli_await_predicate
            (SUB84((double)(float)dVar2,0),this,param_1,param_2,local_68,&local_80,&local_98,0);
  if ((local_98 & 1) != 0) {
    operator_delete(local_88);
  }
  if ((local_80 & 1) != 0) {
    operator_delete((void *)CONCAT17(uStack_69,CONCAT16(uStack_6a,CONCAT51(uStack_6f,uStack_70))));
  }
  if (local_68 == local_48) {
    (*(code *)(*local_48)[4])();
  }
  else if (local_48 != (undefined ***)0x0) {
    (*(code *)(*local_48)[5])();
  }
  *(undefined ***)this = &PTR__cli_wait_flight_started_02ac6778;
  if (*(long *)PTR____stack_chk_guard_02ac0540 != local_38) {
                    /* WARNING: Subroutine does not return */
    ___stack_chk_fail();
  }
  return;
}


// 0006e530  cli_wait_flight_started::~cli_wait_flight_started

/* cli_wait_flight_started::~cli_wait_flight_started() */

void __thiscall cli_wait_flight_started::~cli_wait_flight_started(cli_wait_flight_started *this)

{
  cli_wait_flight_started cVar1;
  cli_wait_flight_started *pcVar2;
  
  *(undefined ***)this = &PTR__cli_await_predicate_02ac80f0;
  if (((byte)this[0xb0] & 1) == 0) {
    if (((byte)this[0x98] & 1) == 0) goto LAB_0006e559;
LAB_0006e5af:
    operator_delete(*(void **)(this + 0xa8));
    pcVar2 = *(cli_wait_flight_started **)(this + 0x80);
    if (this + 0x60 == pcVar2) goto LAB_0006e5cb;
  }
  else {
    operator_delete(*(void **)(this + 0xc0));
    if (((byte)this[0x98] & 1) != 0) goto LAB_0006e5af;
LAB_0006e559:
    pcVar2 = *(cli_wait_flight_started **)(this + 0x80);
    if (this + 0x60 == pcVar2) {
LAB_0006e5cb:
      (**(code **)(*(long *)pcVar2 + 0x20))();
      *(undefined ***)this = &PTR__CLI_command_02afe530;
      cVar1 = this[0x28];
      goto joined_r0x0006e5df;
    }
  }
  if (pcVar2 != (cli_wait_flight_started *)0x0) {
    (**(code **)(*(long *)pcVar2 + 0x28))();
  }
  *(undefined ***)this = &PTR__CLI_command_02afe530;
  cVar1 = this[0x28];
joined_r0x0006e5df:
  if (((byte)cVar1 & 1) != 0) {
    operator_delete(*(void **)(this + 0x38));
  }
  if (((byte)this[8] & 1) == 0) {
    return;
  }
  operator_delete(*(void **)(this + 0x18));
  return;
}


// 0006e600  cli_wait_flight_started::~cli_wait_flight_started

/* cli_wait_flight_started::~cli_wait_flight_started() */

void __thiscall cli_wait_flight_started::~cli_wait_flight_started(cli_wait_flight_started *this)

{
  cli_wait_flight_started cVar1;
  cli_wait_flight_started *pcVar2;
  
  *(undefined ***)this = &PTR__cli_await_predicate_02ac80f0;
  if (((byte)this[0xb0] & 1) == 0) {
    if (((byte)this[0x98] & 1) == 0) goto LAB_0006e629;
LAB_0006e68f:
    operator_delete(*(void **)(this + 0xa8));
    pcVar2 = *(cli_wait_flight_started **)(this + 0x80);
    if (this + 0x60 == pcVar2) goto LAB_0006e6ab;
  }
  else {
    operator_delete(*(void **)(this + 0xc0));
    if (((byte)this[0x98] & 1) != 0) goto LAB_0006e68f;
LAB_0006e629:
    pcVar2 = *(cli_wait_flight_started **)(this + 0x80);
    if (this + 0x60 == pcVar2) {
LAB_0006e6ab:
      (**(code **)(*(long *)pcVar2 + 0x20))();
      *(undefined ***)this = &PTR__CLI_command_02afe530;
      cVar1 = this[0x28];
      goto joined_r0x0006e6bf;
    }
  }
  if (pcVar2 != (cli_wait_flight_started *)0x0) {
    (**(code **)(*(long *)pcVar2 + 0x28))();
  }
  *(undefined ***)this = &PTR__CLI_command_02afe530;
  cVar1 = this[0x28];
joined_r0x0006e6bf:
  if (((byte)cVar1 & 1) != 0) {
    operator_delete(*(void **)(this + 0x38));
  }
  if (((byte)this[8] & 1) != 0) {
    operator_delete(*(void **)(this + 0x18));
  }
  operator_delete(this);
  return;
}


// 0006e6d0  std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>::~__func

/* std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1},
   std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1}>, bool ()>::~__func() */

void __thiscall
std::__function::
__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>
::~__func(__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_,std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_>,bool()>
          *this)

{
  return;
}


// 0006e6e0  std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>::~__func

/* std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1},
   std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1}>, bool ()>::~__func() */

void __thiscall
std::__function::
__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>
::~__func(__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_,std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_>,bool()>
          *this)

{
  operator_delete(this);
  return;
}


// 0006e6f0  std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>::__clone

/* std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1},
   std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1}>, bool ()>::__clone()
   const */

void std::__function::
     __func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>
     ::__clone(void)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02ac67c0;
  return;
}


// 0006e710  std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>::__clone

/* std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1},
   std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1}>, bool
   ()>::__clone(std::__function::__base<bool ()>*) const */

void __thiscall
std::__function::
__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>
::__clone(__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_,std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_>,bool()>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02ac67c0;
  return;
}


// 0006e720  std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>::destroy

/* std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1},
   std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1}>, bool ()>::destroy() */

void std::__function::
     __func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>
     ::destroy(void)

{
  return;
}


// 0006e730  std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>::destroy_deallocate

/* std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1},
   std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1}>, bool
   ()>::destroy_deallocate() */

void __thiscall
std::__function::
__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>
::destroy_deallocate
          (__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_,std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_>,bool()>
           *this)

{
  operator_delete(this);
  return;
}


// 0006e740  std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>::operator()

/* std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1},
   std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1}>, bool
   ()>::TEMPNAMEPLACEHOLDERVALUE() */

byte __thiscall
std::__function::
__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>
::operator()(__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_,std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_>,bool()>
             *this)

{
  byte bVar1;
  
  bVar1 = init_sim::is_flight_in_progress((init_sim *)&_init);
  return bVar1 & (_plot_init_lights & 1) == 0;
}


// 0006e770  std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>::target

/* std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1},
   std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1}>, bool
   ()>::target(std::type_info const&) const */

__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_,std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_>,bool()>
* __thiscall
std::__function::
__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>
::target(__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_,std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_>,bool()>
         *this,type_info *param_1)

{
  __func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_,std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_>,bool()>
  *p_Var1;
  
  p_Var1 = (__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_,std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::_lambda()_1_>,bool()>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN23cli_wait_flight_startedC1EP15CLI_output_pipeRNSt3__16vectorINS2_12basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEENS7_IS9_EEEEEUlvE_"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 0006e790  std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>::target_type

/* std::__function::__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1},
   std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,
   std::vector<std::string, std::allocator<std::string > >&)::{lambda()#1}>, bool ()>::target_type()
   const */

undefined **
std::__function::
__func<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1},std::allocator<cli_wait_flight_started::cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)::{lambda()#1}>,bool()>
::target_type(void)

{
  return &cli_wait_flight_started::
          cli_wait_flight_started(CLI_output_pipe*,std::vector<std::string,std::allocator<std::string>>&)
          ::{lambda()#1}::typeinfo;
}


// 000737f0  std::map<std::string,ATCFlightSegmentType,std::less<std::string>,std::allocator<std::pair<std::string_const,ATCFlightSegmentType>>>::~map

/* std::map<std::string, ATCFlightSegmentType, std::less<std::string >,
   std::allocator<std::pair<std::string const, ATCFlightSegmentType> > >::~map() */

void __thiscall
std::
map<std::string,ATCFlightSegmentType,std::less<std::string>,std::allocator<std::pair<std::string_const,ATCFlightSegmentType>>>
::~map(map<std::string,ATCFlightSegmentType,std::less<std::string>,std::allocator<std::pair<std::string_const,ATCFlightSegmentType>>>
       *this)

{
  __tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
  ::destroy((__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
             *)this,*(__tree_node **)(this + 8));
  return;
}


// 00073fa0  std::__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>::__emplace_hint_unique_key_args<std::string,std::pair<std::string_const,ATCFlightSegmentType>const&>

/* std::pair<std::__tree_iterator<std::__value_type<std::string, ATCFlightSegmentType>,
   std::__tree_node<std::__value_type<std::string, ATCFlightSegmentType>, void*>*, long>, bool>
   std::__tree<std::__value_type<std::string, ATCFlightSegmentType>,
   std::__map_value_compare<std::string, std::__value_type<std::string, ATCFlightSegmentType>,
   std::less<std::string >, true>, std::allocator<std::__value_type<std::string,
   ATCFlightSegmentType> > >::__emplace_hint_unique_key_args<std::string, std::pair<std::string
   const, ATCFlightSegmentType> const&>(std::__tree_const_iterator<std::__value_type<std::string,
   ATCFlightSegmentType>, std::__tree_node<std::__value_type<std::string, ATCFlightSegmentType>,
   void*>*, long>, std::string const&, std::pair<std::string const, ATCFlightSegmentType> const&) */

undefined1  [16] __thiscall
std::
__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
::
__emplace_hint_unique_key_args<std::string,std::pair<std::string_const,ATCFlightSegmentType>const&>
          (__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
           *this,undefined8 param_2,undefined8 param_3,string *param_4)

{
  __tree_node_base **pp_Var1;
  __tree_node_base *p_Var2;
  undefined8 extraout_RDX;
  undefined8 uVar3;
  __tree_node_base *p_Var4;
  undefined1 auVar5 [16];
  undefined1 local_38 [8];
  undefined8 local_30;
  
  pp_Var1 = __find_equal<std::string>(this,param_2,&local_30,local_38,param_3);
  p_Var2 = *pp_Var1;
  if (p_Var2 == (__tree_node_base *)0x0) {
    p_Var2 = operator_new(0x40);
    std::string::string((string *)(p_Var2 + 0x20),param_4);
    *(undefined4 *)(p_Var2 + 0x38) = *(undefined4 *)(param_4 + 0x18);
    *(undefined8 *)p_Var2 = 0;
    *(undefined8 *)(p_Var2 + 8) = 0;
    *(undefined8 *)(p_Var2 + 0x10) = local_30;
    *pp_Var1 = p_Var2;
    p_Var4 = p_Var2;
    if (**(long **)this != 0) {
      *(long *)this = **(long **)this;
      p_Var4 = *pp_Var1;
    }
    __tree_balance_after_insert<std::__tree_node_base<void*>*>
              (*(__tree_node_base **)(this + 8),p_Var4);
    *(long *)(this + 0x10) = *(long *)(this + 0x10) + 1;
    uVar3 = CONCAT71((int7)((ulong)extraout_RDX >> 8),1);
  }
  else {
    uVar3 = 0;
  }
  auVar5._8_8_ = uVar3;
  auVar5._0_8_ = p_Var2;
  return auVar5;
}


// 00074050  std::__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>::__find_equal<std::string>

/* std::__tree_node_base<void*>*& std::__tree<std::__value_type<std::string, ATCFlightSegmentType>,
   std::__map_value_compare<std::string, std::__value_type<std::string, ATCFlightSegmentType>,
   std::less<std::string >, true>, std::allocator<std::__value_type<std::string,
   ATCFlightSegmentType> > >::__find_equal<std::string
   >(std::__tree_const_iterator<std::__value_type<std::string, ATCFlightSegmentType>,
   std::__tree_node<std::__value_type<std::string, ATCFlightSegmentType>, void*>*, long>,
   std::__tree_end_node<std::__tree_node_base<void*>*>*&, std::__tree_node_base<void*>*&,
   std::string const&) */

__tree_node_base ** __thiscall
std::
__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
::__find_equal<std::string>
          (__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
           *this,__tree_node_base *param_2,__tree_end_node **param_3,__tree_node_base **param_4,
          string *param_5)

{
  __tree_node_base _Var1;
  long lVar2;
  int iVar3;
  ulong uVar4;
  __tree_node_base **pp_Var5;
  ulong uVar6;
  string *psVar7;
  ulong uVar8;
  __tree_node_base *p_Var9;
  __tree_node_base *p_Var10;
  __tree_node_base *p_Var11;
  __tree_node_base *p_Var12;
  __tree_node_base *p_Var13;
  ulong uVar14;
  __tree_node_base *p_Var15;
  ulong uVar16;
  
  if ((__tree_node_base *)(this + 8) != param_2) {
    _Var1 = param_2[0x20];
    if (((byte)_Var1 & 1) == 0) {
      p_Var13 = (__tree_node_base *)(ulong)((byte)_Var1 >> 1);
      uVar4 = (ulong)(byte)*param_5;
      if (((byte)*param_5 & 1) != 0) goto LAB_000740a8;
LAB_00074091:
      p_Var10 = (__tree_node_base *)(uVar4 >> 1);
    }
    else {
      p_Var13 = *(__tree_node_base **)(param_2 + 0x28);
      uVar4 = (ulong)(byte)*param_5;
      if (((byte)*param_5 & 1) == 0) goto LAB_00074091;
LAB_000740a8:
      p_Var10 = *(__tree_node_base **)(param_5 + 8);
    }
    p_Var12 = p_Var10;
    if (p_Var13 < p_Var10) {
      p_Var12 = p_Var13;
    }
    if (p_Var12 == (__tree_node_base *)0x0) {
      if (p_Var13 <= p_Var10) {
LAB_0007421d:
        if (p_Var10 <= p_Var13) {
LAB_00074212:
          *param_3 = (__tree_end_node *)param_2;
          *param_4 = param_2;
          return param_4;
        }
LAB_00074222:
        p_Var13 = *(__tree_node_base **)(param_2 + 8);
        p_Var12 = p_Var13;
        if (p_Var13 == (__tree_node_base *)0x0) {
          p_Var15 = *(__tree_node_base **)(param_2 + 0x10);
          p_Var12 = param_2;
          if (*(__tree_node_base **)p_Var15 != param_2) {
            do {
              p_Var12 = *(__tree_node_base **)(p_Var12 + 0x10);
              p_Var15 = *(__tree_node_base **)(p_Var12 + 0x10);
            } while (*(__tree_node_base **)p_Var15 != p_Var12);
          }
        }
        else {
          do {
            p_Var15 = p_Var12;
            p_Var12 = *(__tree_node_base **)p_Var15;
          } while (*(__tree_node_base **)p_Var15 != (__tree_node_base *)0x0);
        }
        if (p_Var15 == (__tree_node_base *)(this + 8)) goto LAB_00074372;
        _Var1 = p_Var15[0x20];
        if (((byte)_Var1 & 1) == 0) {
          p_Var12 = (__tree_node_base *)(ulong)((byte)_Var1 >> 1);
        }
        else {
          p_Var12 = *(__tree_node_base **)(p_Var15 + 0x28);
        }
        p_Var9 = p_Var10;
        if (p_Var12 < p_Var10) {
          p_Var9 = p_Var12;
        }
        if (p_Var9 != (__tree_node_base *)0x0) {
          if ((uVar4 & 1) == 0) {
            psVar7 = param_5 + 1;
            if (((byte)_Var1 & 1) != 0) goto LAB_00074329;
LAB_00074313:
            p_Var11 = p_Var15 + 0x21;
          }
          else {
            psVar7 = *(string **)(param_5 + 0x10);
            if (((byte)_Var1 & 1) == 0) goto LAB_00074313;
LAB_00074329:
            p_Var11 = *(__tree_node_base **)(p_Var15 + 0x30);
          }
          iVar3 = _memcmp(psVar7,p_Var11,(size_t)p_Var9);
          if (iVar3 != 0) {
            if (iVar3 < 0) goto LAB_00074372;
            goto LAB_00074354;
          }
        }
        if (p_Var10 < p_Var12) {
LAB_00074372:
          if (p_Var13 == (__tree_node_base *)0x0) {
            *param_3 = (__tree_end_node *)param_2;
            return (__tree_node_base **)(param_2 + 8);
          }
          *param_3 = (__tree_end_node *)p_Var15;
          return (__tree_node_base **)p_Var15;
        }
        goto LAB_00074354;
      }
    }
    else {
      if ((uVar4 & 1) == 0) {
        psVar7 = param_5 + 1;
      }
      else {
        psVar7 = *(string **)(param_5 + 0x10);
      }
      if (((byte)_Var1 & 1) == 0) {
        p_Var15 = param_2 + 0x21;
      }
      else {
        p_Var15 = *(__tree_node_base **)(param_2 + 0x30);
      }
      iVar3 = _memcmp(psVar7,p_Var15,(size_t)p_Var12);
      if (iVar3 == 0) {
        if (p_Var13 <= p_Var10) goto LAB_000741e9;
      }
      else if (-1 < iVar3) {
LAB_000741e9:
        iVar3 = _memcmp(p_Var15,psVar7,(size_t)p_Var12);
        if (iVar3 == 0) goto LAB_0007421d;
        if (-1 < iVar3) goto LAB_00074212;
        goto LAB_00074222;
      }
    }
  }
  p_Var10 = *(__tree_node_base **)param_2;
  p_Var13 = param_2;
  if (*(__tree_node_base **)this == param_2) goto LAB_00074289;
  p_Var12 = p_Var10;
  if (p_Var10 == (__tree_node_base *)0x0) {
    p_Var13 = param_2 + 0x10;
    if ((__tree_node_base *)**(undefined8 **)(param_2 + 0x10) == param_2) {
      do {
        lVar2 = *(long *)p_Var13;
        p_Var13 = (__tree_node_base *)(lVar2 + 0x10);
      } while (**(long **)(lVar2 + 0x10) == lVar2);
    }
    p_Var13 = *(__tree_node_base **)p_Var13;
    uVar4 = (ulong)(byte)*param_5;
    if (((byte)*param_5 & 1) == 0) goto LAB_0007419b;
LAB_00074154:
    uVar16 = *(ulong *)(param_5 + 8);
    uVar6 = (ulong)(byte)p_Var13[0x20];
    if (((byte)p_Var13[0x20] & 1) == 0) goto LAB_00074161;
LAB_000741aa:
    uVar14 = *(ulong *)(p_Var13 + 0x28);
  }
  else {
    do {
      p_Var13 = p_Var12;
      p_Var12 = *(__tree_node_base **)(p_Var13 + 8);
    } while (*(__tree_node_base **)(p_Var13 + 8) != (__tree_node_base *)0x0);
    uVar4 = (ulong)(byte)*param_5;
    if (((byte)*param_5 & 1) != 0) goto LAB_00074154;
LAB_0007419b:
    uVar16 = uVar4 >> 1;
    uVar6 = (ulong)(byte)p_Var13[0x20];
    if (((byte)p_Var13[0x20] & 1) != 0) goto LAB_000741aa;
LAB_00074161:
    uVar14 = uVar6 >> 1;
  }
  uVar8 = uVar14;
  if (uVar16 < uVar14) {
    uVar8 = uVar16;
  }
  if (uVar8 != 0) {
    if ((uVar6 & 1) == 0) {
      p_Var12 = p_Var13 + 0x21;
    }
    else {
      p_Var12 = *(__tree_node_base **)(p_Var13 + 0x30);
    }
    if ((uVar4 & 1) == 0) {
      psVar7 = param_5 + 1;
    }
    else {
      psVar7 = *(string **)(param_5 + 0x10);
    }
    iVar3 = _memcmp(p_Var12,psVar7,uVar8);
    if (iVar3 != 0) {
      if (-1 < iVar3) goto LAB_00074354;
      goto LAB_00074289;
    }
  }
  if (uVar16 <= uVar14) {
LAB_00074354:
    pp_Var5 = __find_equal<std::string>(this,param_3,param_5);
    return pp_Var5;
  }
LAB_00074289:
  if (p_Var10 == (__tree_node_base *)0x0) {
    *param_3 = (__tree_end_node *)param_2;
  }
  else {
    *param_3 = (__tree_end_node *)p_Var13;
    param_2 = p_Var13 + 8;
  }
  return (__tree_node_base **)param_2;
}


// 000743a0  std::__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>::__find_equal<std::string>

/* std::__tree_node_base<void*>*& std::__tree<std::__value_type<std::string, ATCFlightSegmentType>,
   std::__map_value_compare<std::string, std::__value_type<std::string, ATCFlightSegmentType>,
   std::less<std::string >, true>, std::allocator<std::__value_type<std::string,
   ATCFlightSegmentType> > >::__find_equal<std::string
   >(std::__tree_end_node<std::__tree_node_base<void*>*>*&, std::string const&) */

__tree_node_base ** __thiscall
std::
__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
::__find_equal<std::string>
          (__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
           *this,__tree_end_node **param_1,string *param_2)

{
  __tree_node_base _Var1;
  int iVar2;
  ulong uVar3;
  string *psVar4;
  ulong uVar5;
  __tree_node_base *p_Var6;
  __tree_node_base *p_Var7;
  __tree_node_base *p_Var8;
  ulong uVar9;
  
  p_Var8 = *(__tree_node_base **)(this + 8);
  p_Var6 = (__tree_node_base *)(this + 8);
  if (p_Var8 == (__tree_node_base *)0x0) {
    *param_1 = (__tree_end_node *)p_Var6;
  }
  else {
    p_Var7 = p_Var6;
    if (((byte)*param_2 & 1) == 0) {
      uVar3 = (ulong)((byte)*param_2 >> 1);
      psVar4 = param_2 + 1;
    }
    else {
      uVar3 = *(ulong *)(param_2 + 8);
      psVar4 = *(string **)(param_2 + 0x10);
    }
    do {
      while( true ) {
        p_Var6 = p_Var8;
        _Var1 = p_Var6[0x20];
        if (((byte)_Var1 & 1) == 0) {
          uVar9 = (ulong)((byte)_Var1 >> 1);
        }
        else {
          uVar9 = *(ulong *)(p_Var6 + 0x28);
        }
        uVar5 = uVar3;
        if (uVar9 < uVar3) {
          uVar5 = uVar9;
        }
        if (uVar5 != 0) break;
        if (uVar3 < uVar9) goto LAB_000743f0;
LAB_000744c0:
        if (uVar3 <= uVar9) {
LAB_000744ed:
          *param_1 = (__tree_end_node *)p_Var6;
          return (__tree_node_base **)p_Var7;
        }
LAB_000744c5:
        p_Var7 = p_Var6 + 8;
        p_Var8 = *(__tree_node_base **)(p_Var6 + 8);
        if (*(__tree_node_base **)(p_Var6 + 8) == (__tree_node_base *)0x0) {
          *param_1 = (__tree_end_node *)p_Var6;
          return (__tree_node_base **)(p_Var6 + 8);
        }
      }
      if (((byte)_Var1 & 1) == 0) {
        p_Var8 = p_Var6 + 0x21;
      }
      else {
        p_Var8 = *(__tree_node_base **)(p_Var6 + 0x30);
      }
      iVar2 = _memcmp(psVar4,p_Var8,uVar5);
      if (iVar2 == 0) {
        if (uVar9 <= uVar3) goto LAB_000744a0;
      }
      else if (-1 < iVar2) {
LAB_000744a0:
        iVar2 = _memcmp(p_Var8,psVar4,uVar5);
        if (iVar2 == 0) goto LAB_000744c0;
        if (-1 < iVar2) goto LAB_000744ed;
        goto LAB_000744c5;
      }
LAB_000743f0:
      p_Var7 = p_Var6;
      p_Var8 = *(__tree_node_base **)p_Var6;
    } while (*(__tree_node_base **)p_Var6 != (__tree_node_base *)0x0);
    *param_1 = (__tree_end_node *)p_Var6;
  }
  return (__tree_node_base **)p_Var6;
}


// 00074510  std::__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>::destroy

/* std::__tree<std::__value_type<std::string, ATCFlightSegmentType>,
   std::__map_value_compare<std::string, std::__value_type<std::string, ATCFlightSegmentType>,
   std::less<std::string >, true>, std::allocator<std::__value_type<std::string,
   ATCFlightSegmentType> > >::destroy(std::__tree_node<std::__value_type<std::string,
   ATCFlightSegmentType>, void*>*) */

void __thiscall
std::
__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
::destroy(__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
          *this,__tree_node *param_1)

{
  if (param_1 != (__tree_node *)0x0) {
    destroy(this,*(__tree_node **)param_1);
    destroy(this,*(__tree_node **)(param_1 + 8));
    if (((byte)param_1[0x20] & 1) != 0) {
      operator_delete(*(void **)(param_1 + 0x30));
    }
    operator_delete(param_1);
    return;
  }
  return;
}


// 00074560  std::__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>::find<std::string>

/* std::__tree_const_iterator<std::__value_type<std::string, ATCFlightSegmentType>,
   std::__tree_node<std::__value_type<std::string, ATCFlightSegmentType>, void*>*, long>
   std::__tree<std::__value_type<std::string, ATCFlightSegmentType>,
   std::__map_value_compare<std::string, std::__value_type<std::string, ATCFlightSegmentType>,
   std::less<std::string >, true>, std::allocator<std::__value_type<std::string,
   ATCFlightSegmentType> > >::find<std::string >(std::string const&) const */

__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
* __thiscall
std::
__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
::find<std::string>(__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
                    *this,string *param_1)

{
  __tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
  _Var1;
  uint uVar2;
  int iVar3;
  ulong uVar4;
  __tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
  *p_Var5;
  ulong uVar6;
  ulong uVar7;
  __tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
  *p_Var8;
  string *psVar9;
  
  p_Var5 = *(__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
             **)(this + 8);
  if (((byte)*param_1 & 1) == 0) {
    uVar7 = (ulong)((byte)*param_1 >> 1);
    psVar9 = param_1 + 1;
  }
  else {
    uVar7 = *(ulong *)(param_1 + 8);
    psVar9 = *(string **)(param_1 + 0x10);
  }
  if (p_Var5 != (__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
                 *)0x0) {
    p_Var8 = this + 8;
    do {
      _Var1 = p_Var5[0x20];
      if (((byte)_Var1 & 1) == 0) {
        uVar6 = (ulong)((byte)_Var1 >> 1);
      }
      else {
        uVar6 = *(ulong *)(p_Var5 + 0x28);
      }
      uVar4 = uVar6;
      if (uVar7 < uVar6) {
        uVar4 = uVar7;
      }
      if (uVar4 == 0) {
LAB_000745c0:
        uVar2 = (uint)(uVar7 < uVar6);
        if (uVar6 < uVar7) {
          uVar2 = 0xffffffff;
        }
      }
      else {
        if (((byte)_Var1 & 1) == 0) {
          uVar2 = _memcmp(p_Var5 + 0x21,psVar9,uVar4);
        }
        else {
          uVar2 = _memcmp(*(void **)(p_Var5 + 0x30),psVar9,uVar4);
        }
        if (uVar2 == 0) goto LAB_000745c0;
      }
      if (-1 < (int)uVar2) {
        p_Var8 = p_Var5;
      }
      p_Var5 = *(__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
                 **)(p_Var5 + (ulong)(uVar2 >> 0x1f) * 8);
    } while (p_Var5 != (__tree<std::__value_type<std::string,ATCFlightSegmentType>,std::__map_value_compare<std::string,std::__value_type<std::string,ATCFlightSegmentType>,std::less<std::string>,true>,std::allocator<std::__value_type<std::string,ATCFlightSegmentType>>>
                        *)0x0);
    if (p_Var8 != this + 8) {
      _Var1 = p_Var8[0x20];
      if (((byte)_Var1 & 1) == 0) {
        uVar6 = (ulong)((byte)_Var1 >> 1);
      }
      else {
        uVar6 = *(ulong *)(p_Var8 + 0x28);
      }
      uVar4 = uVar7;
      if (uVar6 < uVar7) {
        uVar4 = uVar6;
      }
      if (uVar4 != 0) {
        if (((byte)_Var1 & 1) == 0) {
          iVar3 = _memcmp(psVar9,p_Var8 + 0x21,uVar4);
        }
        else {
          iVar3 = _memcmp(psVar9,*(void **)(p_Var8 + 0x30),uVar4);
        }
        if (iVar3 != 0) {
          if (-1 < iVar3) {
            return p_Var8;
          }
          goto LAB_0007468f;
        }
      }
      if (uVar6 <= uVar7) {
        return p_Var8;
      }
    }
  }
LAB_0007468f:
  return this + 8;
}


// 000f63d0  plot_init_lights_v11

/* WARNING: Removing unreachable block (ram,0x000f65c3) */
/* WARNING: Removing unreachable block (ram,0x000f65d5) */
/* WARNING: Type propagation algorithm not settling */
/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* plot_init_lights_v11(std::string const&, float) */

void plot_init_lights_v11(string *param_1,float param_2)

{
  int iVar1;
  ui_screen_loading *this;
  mersenne_twister_engine *pmVar2;
  void *pvVar3;
  long lVar4;
  long lVar5;
  ushort local_a0 [8];
  void *local_90;
  ushort local_88 [8];
  void *local_78;
  ushort local_70 [8];
  void *local_60;
  ulong local_58;
  undefined8 uStack_50;
  void *local_48;
  uint local_40;
  int local_3c;
  void *local_30;
  float local_24;
  
  local_24 = param_2;
  if (s_init_lights_screen == (ui_screen_loading *)0x0) {
    this = operator_new(0x198);
    ui_screen_loading::ui_screen_loading(this,true);
    lVar4 = DAT_0315daa8 - _tip_message_1;
  }
  else {
    lVar4 = DAT_0315daa8 - _tip_message_1;
    this = s_init_lights_screen;
  }
  s_init_lights_screen = this;
  if (lVar4 != 0) {
    if ((double)local_24 < DAT_025251f0) {
      if (_msgIdx == -1) {
        iVar1 = (int)(lVar4 >> 3) * -0x55555555 + -1;
        if (iVar1 == 0) {
          _msgIdx = 0;
        }
        else {
          local_40 = 0;
          local_3c = iVar1;
          pmVar2 = (mersenne_twister_engine *)rand_gen();
          _msgIdx = std::uniform_int_distribution<int>::operator()
                              ((uniform_int_distribution<int> *)&local_40,pmVar2,
                               (param_type *)&local_40);
        }
      }
      lVar4 = (long)_msgIdx * 0x18;
      ui_screen_loading::set_tip_message
                (s_init_lights_screen,(string *)(_tip_message_1 + lVar4),
                 (string *)(_tip_message_2 + lVar4),(string *)(_tip_message_3 + lVar4),
                 (string *)(lVar4 + _tip_message_4));
    }
    else {
      pvVar3 = operator_new(0xd0);
      local_58 = _DAT_02525360;
      uStack_50 = _UNK_02525368;
      local_48 = pvVar3;
      _memcpy(pvVar3,s_Follow_us_on_social_media___XPla_0278e82e,0xc0);
      *(undefined1 *)((long)pvVar3 + 0xc0) = 0;
      UTL_translate_string((string *)&local_40,(int)&local_58,(string *)0x0);
      local_a0[0] = 0;
      local_88[0] = 0;
      local_70[0] = 0;
      ui_screen_loading::set_tip_message
                (this,(string *)&local_40,(string *)local_a0,(string *)local_88,(string *)local_70);
      if ((local_70[0] & 1) != 0) {
        operator_delete(local_60);
      }
      if ((local_88[0] & 1) != 0) {
        operator_delete(local_78);
      }
      if ((local_a0[0] & 1) != 0) {
        operator_delete(local_90);
      }
      if ((local_40 & 1) != 0) {
        operator_delete(local_30);
      }
      if ((local_58 & 1) != 0) {
        operator_delete(local_48);
      }
      _msgIdx = -1;
    }
  }
  ui_screen_loading::update(s_init_lights_screen,param_1,local_24);
  update_loading_advertisement();
  MACIBM_push_v11_init_lights_screen();
  run_gui_and_nothing_else_one_frame(0);
  lVar4 = DAT_0315db10;
  _s_init_lights_stack_depth = _s_init_lights_stack_depth + -1;
  if (_s_init_lights_stack_depth == 0) {
    lVar5 = 0;
    while (lVar5 + -0x10 != -0x20) {
      restore_from_modal_state
                (*(int *)(lVar4 + -8 + lVar5),*(gui_widget_controller **)(lVar4 + -0x10 + lVar5));
      lVar5 = lVar5 + -0x10;
    }
    DAT_0315db10 = lVar4 + -0x10;
  }
  return;
}


// 000f6760  std::vector<v11_init_lights_stack,std::allocator<v11_init_lights_stack>>::~vector

/* std::vector<v11_init_lights_stack, std::allocator<v11_init_lights_stack> >::~vector() */

void __thiscall
std::vector<v11_init_lights_stack,std::allocator<v11_init_lights_stack>>::~vector
          (vector<v11_init_lights_stack,std::allocator<v11_init_lights_stack>> *this)

{
  long lVar1;
  long lVar2;
  
  lVar1 = *(long *)this;
  if (lVar1 != 0) {
    for (lVar2 = *(long *)(this + 8); lVar2 != lVar1; lVar2 = lVar2 + -0x10) {
      restore_from_modal_state(*(int *)(lVar2 + -8),*(gui_widget_controller **)(lVar2 + -0x10));
    }
    *(long *)(this + 8) = lVar1;
    operator_delete(*(void **)this);
    return;
  }
  return;
}


// 000f67d0  MACIBM_push_v11_init_lights_screen

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* WARNING: Unknown calling convention -- yet parameter storage is locked */
/* MACIBM_push_v11_init_lights_screen() */

void MACIBM_push_v11_init_lights_screen(void)

{
  int iVar1;
  ulong uVar2;
  undefined8 uVar3;
  undefined8 *puVar4;
  undefined8 *puVar5;
  undefined8 *puVar6;
  undefined8 uVar7;
  void *pvVar8;
  undefined8 *puVar9;
  undefined8 *puVar10;
  undefined8 *puVar11;
  char *in_RDI;
  long lVar12;
  ulong uVar13;
  bool bVar14;
  
  puVar6 = DAT_0315db10;
  uVar3 = s_init_lights_screen;
  iVar1 = _s_init_lights_stack_depth + 1;
  bVar14 = _s_init_lights_stack_depth == 0;
  _s_init_lights_stack_depth = iVar1;
  if (bVar14) {
    if (DAT_0315db10 < DAT_0315db18) {
      uVar7 = gui_widget_controller::get_root_controller();
      *puVar6 = uVar7;
      *(undefined4 *)(puVar6 + 1) = *_wins;
      _DAT_0315d4a0 = 0x3df;
      gui_widget_controller::set_root_controller(uVar3,1);
      DAT_0315db10 = puVar6 + 2;
    }
    else {
      lVar12 = (long)DAT_0315db10 - (long)_s_init_lights_stack >> 4;
      uVar2 = lVar12 + 1;
      if (uVar2 >> 0x3c != 0) {
        std::__vector_base<v11_init_lights_stack,std::allocator<v11_init_lights_stack>>::
        __throw_length_error();
LAB_000f69a9:
                    /* WARNING: Subroutine does not return */
        std::__throw_length_error(in_RDI);
      }
      uVar13 = (long)DAT_0315db18 - (long)_s_init_lights_stack >> 3;
      if (uVar13 < uVar2) {
        uVar13 = uVar2;
      }
      if (0x7fffffffffffffe < (ulong)((long)DAT_0315db18 - (long)_s_init_lights_stack >> 4)) {
        uVar13 = 0xfffffffffffffff;
      }
      if (uVar13 == 0) {
        pvVar8 = (void *)0x0;
      }
      else {
        if (0xfffffffffffffff < uVar13) goto LAB_000f69a9;
        pvVar8 = operator_new(uVar13 << 4);
      }
      uVar3 = s_init_lights_screen;
      uVar7 = gui_widget_controller::get_root_controller();
      lVar12 = lVar12 * 0x10;
      puVar11 = (undefined8 *)((long)pvVar8 + lVar12);
      *puVar11 = uVar7;
      *(undefined4 *)((long)pvVar8 + lVar12 + 8) = *_wins;
      _DAT_0315d4a0 = 0x3df;
      gui_widget_controller::set_root_controller(uVar3,1);
      puVar5 = _s_init_lights_stack;
      DAT_0315db18 = (undefined8 *)((long)pvVar8 + uVar13 * 0x10);
      puVar6 = puVar11 + 2;
      puVar4 = _s_init_lights_stack;
      puVar9 = _s_init_lights_stack;
      for (puVar10 = DAT_0315db10; _s_init_lights_stack = puVar11, puVar10 != puVar5;
          puVar10 = puVar10 + -2) {
        uVar3 = puVar10[-1];
        _s_init_lights_stack = puVar4;
        puVar11[-2] = puVar10[-2];
        puVar11[-1] = uVar3;
        puVar11 = puVar11 + -2;
        puVar4 = _s_init_lights_stack;
        puVar9 = DAT_0315db10;
      }
      for (; DAT_0315db10 = puVar6, puVar9 != puVar4; puVar9 = puVar9 + -2) {
        restore_from_modal_state(*(int *)(puVar9 + -1),(gui_widget_controller *)puVar9[-2]);
        puVar6 = DAT_0315db10;
      }
      if (puVar4 != (undefined8 *)0x0) {
        operator_delete(puVar4);
        return;
      }
    }
  }
  return;
}


// 00156250  std::__vector_base<v11_init_lights_stack,std::allocator<v11_init_lights_stack>>::__throw_length_error

/* std::__vector_base<v11_init_lights_stack, std::allocator<v11_init_lights_stack>
   >::__throw_length_error() const */

void std::__vector_base<v11_init_lights_stack,std::allocator<v11_init_lights_stack>>::
     __throw_length_error(void)

{
                    /* WARNING: Subroutine does not return */
  std::__vector_base_common<true>::__throw_length_error();
}


// 0015e1b0  ATCPilotMenuItemFlightPlanForm::IsCommandReady

/* ATCPilotMenuItemFlightPlanForm::IsCommandReady(ATCAircraft*, ATCController*) const */

bool ATCPilotMenuItemFlightPlanForm::IsCommandReady(ATCAircraft *param_1,ATCController *param_2)

{
  int iVar1;
  
  iVar1 = ATCAircraft::GetStatus((ATCAircraft *)param_2);
  return 0 < iVar1;
}


// 0015e1d0  ATCPilotMenuItemFlightPlanForm::DoCommand

/* ATCPilotMenuItemFlightPlanForm::DoCommand(ATCController*, std::vector<int, std::allocator<int> >
   const&) const */

undefined8 ATCPilotMenuItemFlightPlanForm::DoCommand(ATCController *param_1,vector *param_2)

{
  undefined8 *puVar1;
  size_t in_RCX;
  void *in_RDX;
  void *extraout_RDX;
  undefined8 *puVar2;
  int iVar3;
  int in_R8D;
  
  iVar3 = (int)param_2;
  puVar2 = DAT_0315ec30;
  if (DAT_0315ec30 != &_s_file_flight_plan_postcards) {
    do {
      UTL_postcard::send((UTL_postcard *)(puVar2 + 2),iVar3,in_RDX,in_RCX,in_R8D);
      puVar1 = puVar2 + 1;
      in_RDX = extraout_RDX;
      puVar2 = (undefined8 *)*puVar1;
    } while ((undefined8 *)*puVar1 != &_s_file_flight_plan_postcards);
  }
  return 0;
}


// 0015e210  ATCPilotMenuItemFlightPlanForm::IsSubItemValid

/* ATCPilotMenuItemFlightPlanForm::IsSubItemValid(ATCController*, ATCPilotMenuParameter const&,
   std::vector<ATCPilotMenuParameter const*, std::allocator<ATCPilotMenuParameter const*> > const&)
   const */

undefined1
ATCPilotMenuItemFlightPlanForm::IsSubItemValid
          (ATCController *param_1,ATCPilotMenuParameter *param_2,vector *param_3)

{
  return 1;
}


// 0016f0a0  ATCPilotMenuItemRequestFlightFollowing::IsCommandReady

/* WARNING: Removing unreachable block (ram,0x0016f0e2) */
/* WARNING: Removing unreachable block (ram,0x0016f0f4) */
/* ATCPilotMenuItemRequestFlightFollowing::IsCommandReady(ATCAircraft*, ATCController*) const */

undefined4 __thiscall
ATCPilotMenuItemRequestFlightFollowing::IsCommandReady
          (ATCPilotMenuItemRequestFlightFollowing *this,ATCAircraft *param_1,ATCController *param_2)

{
  undefined4 uVar1;
  
  if (param_2 == (ATCController *)0x0) {
    uVar1 = 2;
  }
  else {
    uVar1 = 1;
    if (*(long *)(param_1 + 0x270) == 0) {
      uVar1 = ATCController::ValidateRequestFlightFollowing
                        ((ATCAircraft *)param_2,(shared_ptr *)param_1,true);
    }
  }
  return uVar1;
}


// 0016f130  ATCController::CmdRequestFlightFollowing

/* ATCController::CmdRequestFlightFollowing(ATCAircraft*, std::shared_ptr<ATCController>&, bool,
   std::vector<std::pair<ATCPilotMenuParameter::eOptionType, ATCPilotMenuParameter::ChoiceData>,
   std::allocator<std::pair<ATCPilotMenuParameter::eOptionType, ATCPilotMenuParameter::ChoiceData> >
   > const&) */

ATCController * __thiscall
ATCController::CmdRequestFlightFollowing
          (ATCController *this,ATCAircraft *param_1,shared_ptr *param_2,bool param_3,vector *param_4
          )

{
  __shared_weak_count *p_Var1;
  long *plVar2;
  ATCAircraft *pAVar3;
  long lVar4;
  __shared_weak_count *this_00;
  undefined8 uVar5;
  int iVar6;
  long *plVar7;
  long *plVar8;
  _Unwind_Exception *exception_object;
  undefined7 in_register_00000009;
  undefined8 *puVar9;
  vector *pvVar10;
  bool extraout_DL;
  shared_ptr *psVar11;
  undefined8 local_48;
  long *local_40;
  shared_ptr *local_38;
  
  puVar9 = (undefined8 *)CONCAT71(in_register_00000009,param_3);
  *puVar9 = 0;
  this_00 = (__shared_weak_count *)puVar9[1];
  puVar9[1] = 0;
  local_38 = param_2;
  if (this_00 != (__shared_weak_count *)0x0) {
    LOCK();
    p_Var1 = this_00 + 8;
    lVar4 = *(long *)p_Var1;
    *(long *)p_Var1 = *(long *)p_Var1 + -1;
    UNLOCK();
    if (lVar4 == 0) {
      (**(code **)(*(long *)this_00 + 0x10))(this_00);
      std::__shared_weak_count::__release_weak();
    }
  }
  pvVar10 = (vector *)0x0;
  iVar6 = ValidateRequestFlightFollowing(param_1,local_38,param_3);
  if (iVar6 == 0) {
    if ((char)param_4 == '\0') {
      psVar11 = (shared_ptr *)0x0;
      iVar6 = (**(code **)(*(long *)local_38 + 0x388))();
      if (iVar6 != 0) {
        if (*(long *)(param_1 + 0x48) != 0) {
          uVar5 = *(undefined8 *)(param_1 + 0x40);
          plVar7 = (long *)std::__shared_weak_count::lock();
          if (plVar7 != (long *)0x0) {
            plVar8 = operator_new(0x80);
            plVar8[1] = 0;
            plVar8[2] = 0;
            *plVar8 = (long)&PTR____shared_ptr_emplace_02acf788;
            local_48 = uVar5;
            local_40 = plVar7;
            ATCTaskRequestFlightFollowing::ATCTaskRequestFlightFollowing
                      ((ATCTaskRequestFlightFollowing *)(float)DAT_0315d538,plVar8 + 3,&local_48,
                       local_38);
            LOCK();
            plVar2 = plVar7 + 1;
            lVar4 = *plVar2;
            *plVar2 = *plVar2 + -1;
            UNLOCK();
            if (lVar4 == 0) {
              (**(code **)(*plVar7 + 0x10))(plVar7);
              std::__shared_weak_count::__release_weak();
            }
            *(undefined4 *)this = 0;
            *(long **)(this + 8) = plVar8 + 3;
            *(long **)(this + 0x10) = plVar8;
            LOCK();
            plVar8[1] = plVar8[1] + 1;
            UNLOCK();
            LOCK();
            plVar7 = plVar8 + 1;
            lVar4 = *plVar7;
            *plVar7 = *plVar7 + -1;
            UNLOCK();
            if (lVar4 != 0) {
              return this;
            }
            (**(code **)(*plVar8 + 0x10))(plVar8);
            std::__shared_weak_count::__release_weak();
            return this;
          }
        }
        exception_object = (_Unwind_Exception *)std::__throw_bad_weak_ptr();
        LOCK();
        pAVar3 = param_1 + 8;
        lVar4 = *(long *)pAVar3;
        *(long *)pAVar3 = *(long *)pAVar3 + -1;
        UNLOCK();
        if (lVar4 == 0) {
          CmdRequestFlightFollowing(param_1,psVar11,extraout_DL,pvVar10);
        }
        std::__shared_weak_count::~__shared_weak_count(this_00);
        operator_delete(this_00);
                    /* WARNING: Subroutine does not return */
        __Unwind_Resume(exception_object);
      }
    }
    *(undefined4 *)this = 0;
  }
  else {
    *(int *)this = iVar6;
  }
  *(undefined8 *)(this + 8) = 0;
  *(undefined8 *)(this + 0x10) = 0;
  return this;
}


// 0016f330  ATCPilotMenuItemRequestFlightFollowing::DoCommand

/* ATCPilotMenuItemRequestFlightFollowing::DoCommand(ATCController*, std::vector<int,
   std::allocator<int> > const&) const */

int ATCPilotMenuItemRequestFlightFollowing::DoCommand(ATCController *param_1,vector *param_2)

{
  void *pvVar1;
  vector *pvVar2;
  void *pvVar3;
  int iVar4;
  void *local_48;
  void *local_40;
  
  pvVar2 = _gUsersAircraft;
  iVar4 = 1;
  if ((param_2 != (vector *)0x0) && (_gUsersAircraft != (vector *)0x0)) {
    ATCPilotMenuItem::GetChosenItems((vector *)&local_48);
    iVar4 = ATCAircraft::PilotCmdRequestFlightFollowing(pvVar2);
    pvVar3 = local_48;
    if (local_48 != (void *)0x0) {
      while (pvVar1 = local_40, pvVar1 != pvVar3) {
        local_40 = (void *)((long)pvVar1 + -0x28);
        if ((*(byte *)((long)pvVar1 + -0x20) & 1) != 0) {
          operator_delete(*(void **)((long)pvVar1 + -0x10));
        }
      }
      local_40 = pvVar3;
      operator_delete(local_48);
    }
    if (iVar4 == 3) {
      ATCController::SilenceAircraft((ATCController *)param_2,(ATCAircraft *)_gUsersAircraft);
      iVar4 = 3;
    }
  }
  return iVar4;
}


// 0016f420  ATCAircraft::PilotCmdRequestFlightFollowing

/* ATCAircraft::PilotCmdRequestFlightFollowing(std::vector<std::pair<ATCPilotMenuParameter::eOptionType,
   ATCPilotMenuParameter::ChoiceData>, std::allocator<std::pair<ATCPilotMenuParameter::eOptionType,
   ATCPilotMenuParameter::ChoiceData> > > const&) */

int ATCAircraft::PilotCmdRequestFlightFollowing(vector *param_1)

{
  long *plVar1;
  long *plVar2;
  __tree_node *p_Var3;
  long lVar4;
  ATCRadio *this;
  int iVar5;
  char cVar6;
  int iVar7;
  undefined4 uVar8;
  float fVar9;
  int local_1d0 [2];
  undefined8 local_1c8;
  long *plStack_1c0;
  int local_7c;
  undefined8 local_78;
  long *plStack_70;
  ATCAircraft *local_68;
  long *local_60;
  __tree_node *local_58;
  __tree_node *p_Stack_50;
  undefined8 local_48;
  int local_34;
  
  ATCControllerDb::FindListeningController((ATCAircraft *)&local_68,SUB81(_gControllerDb,0));
  if (local_68 == (ATCAircraft *)0x0) {
    iVar7 = 2;
    goto LAB_0016f72d;
  }
  if (_gUsersAircraft == param_1) {
    cVar6 = ATCRadio::IsP0Talking(_gRadio,&local_7c);
    iVar7 = 1;
    if (cVar6 != '\0') goto LAB_0016f72d;
  }
  this = _gRadio;
  local_34 = 3;
  local_78 = 0;
  plStack_70 = (long *)0x0;
  iVar7 = (**(code **)(*(long *)param_1 + 0x388))(param_1,1);
  fVar9 = 0.0;
  if (_gUsersAircraft != param_1) {
    fVar9 = DAT_02520bf0;
  }
  cVar6 = ATCRadio::IsChanOpen(this,(ATCAircraft *)param_1,iVar7,fVar9);
  iVar7 = 3;
  if (cVar6 == '\0') {
LAB_0016f5bc:
    if ((iVar7 == 3) && (iVar5 = 3, _gUsersAircraft == param_1)) goto LAB_0016f646;
  }
  else {
    local_58 = (__tree_node *)0x0;
    p_Stack_50 = (__tree_node *)0x0;
    ATCController::CmdRequestFlightFollowing
              ((ATCController *)local_1d0,local_68,(shared_ptr *)param_1,SUB81(&local_58,0),
               (vector *)0x0);
    plVar2 = plStack_70;
    plStack_70 = plStack_1c0;
    local_78 = local_1c8;
    local_34 = local_1d0[0];
    local_1c8 = 0;
    plStack_1c0 = (long *)0x0;
    if (plVar2 != (long *)0x0) {
      LOCK();
      plVar1 = plVar2 + 1;
      lVar4 = *plVar1;
      *plVar1 = *plVar1 + -1;
      UNLOCK();
      if (lVar4 == 0) {
        (**(code **)(*plVar2 + 0x10))(plVar2);
        std::__shared_weak_count::__release_weak();
        if (plStack_1c0 != (long *)0x0) {
          LOCK();
          plVar2 = plStack_1c0 + 1;
          lVar4 = *plVar2;
          *plVar2 = *plVar2 + -1;
          UNLOCK();
          if (lVar4 == 0) {
            (**(code **)(*plStack_1c0 + 0x10))(plStack_1c0);
            std::__shared_weak_count::__release_weak();
          }
        }
      }
    }
    if (local_34 != 0) {
      log_request_failure((ATCAircraft *)param_1,param_1,&local_68,&local_58,local_34,
                          "RequestFlightFollowing");
    }
    iVar7 = local_34;
    if (p_Stack_50 != (__tree_node *)0x0) {
      LOCK();
      p_Var3 = p_Stack_50 + 8;
      lVar4 = *(long *)p_Var3;
      *(long *)p_Var3 = *(long *)p_Var3 + -1;
      UNLOCK();
      if (lVar4 == 0) {
        (**(code **)(*(long *)p_Stack_50 + 0x10))(p_Stack_50);
        std::__shared_weak_count::__release_weak();
        iVar7 = local_34;
      }
    }
    local_34 = iVar7;
    if (iVar7 != 0) goto LAB_0016f5bc;
    iVar5 = 0;
LAB_0016f646:
    iVar7 = iVar5;
    ::ATCTxon::ATCTxon((ATCTxon *)local_1d0,(ATCAircraft *)param_1,(shared_ptr *)&local_68,
                       (shared_ptr *)&local_78,false);
    cVar6 = ATCController::IsOurAircraft((ATCController *)local_68,(ATCAircraft *)param_1);
    if (cVar6 == '\0') {
      local_1d0[0] = 1;
    }
    ::ATCTxon::RequestFlightFollowing((ATCTxon *)local_1d0,(ATCAircraft *)param_1);
    uVar8 = (**(code **)(*(long *)param_1 + 0x388))(param_1,1);
    local_58 = operator_new(0x20);
    *(undefined4 *)(local_58 + 0x1c) = uVar8;
    *(undefined8 *)local_58 = 0;
    *(undefined8 *)(local_58 + 8) = 0;
    *(__tree_node ***)(local_58 + 0x10) = &p_Stack_50;
    local_58[0x18] = (__tree_node)0x1;
    local_48 = 1;
    p_Stack_50 = local_58;
    ATCRadio::Transmit((set *)_gRadio,(ATCTxon *)&local_58);
    std::__tree<int,std::less<int>,std::allocator<int>>::destroy
              ((__tree<int,std::less<int>,std::allocator<int>> *)&local_58,p_Stack_50);
    ::ATCTxon::~ATCTxon((ATCTxon *)local_1d0);
  }
  if (plStack_70 != (long *)0x0) {
    LOCK();
    plVar2 = plStack_70 + 1;
    lVar4 = *plVar2;
    *plVar2 = *plVar2 + -1;
    UNLOCK();
    if (lVar4 == 0) {
      (**(code **)(*plStack_70 + 0x10))(plStack_70);
      std::__shared_weak_count::__release_weak();
    }
  }
LAB_0016f72d:
  if (local_60 != (long *)0x0) {
    LOCK();
    plVar2 = local_60 + 1;
    lVar4 = *plVar2;
    *plVar2 = *plVar2 + -1;
    UNLOCK();
    if (lVar4 == 0) {
      (**(code **)(*local_60 + 0x10))(local_60);
      std::__shared_weak_count::__release_weak();
    }
  }
  return iVar7;
}


// 0016f840  ATCPilotMenuItemRequestFlightFollowing::IsSubItemValid

/* ATCPilotMenuItemRequestFlightFollowing::IsSubItemValid(ATCController*, ATCPilotMenuParameter
   const&, std::vector<ATCPilotMenuParameter const*, std::allocator<ATCPilotMenuParameter const*> >
   const&) const */

undefined1
ATCPilotMenuItemRequestFlightFollowing::IsSubItemValid
          (ATCController *param_1,ATCPilotMenuParameter *param_2,vector *param_3)

{
  return 1;
}


// 0016f850  ATCController::ValidateRequestFlightFollowing

/* ATCController::ValidateRequestFlightFollowing(ATCAircraft*, std::shared_ptr<ATCController>&,
   bool) */

char ATCController::ValidateRequestFlightFollowing
               (ATCAircraft *param_1,shared_ptr *param_2,bool param_3)

{
  long *plVar1;
  float fVar2;
  long lVar3;
  long *plVar4;
  long *plVar5;
  char cVar6;
  int iVar7;
  int *piVar8;
  ATCAircraft *pAVar9;
  undefined7 in_register_00000011;
  char cVar10;
  
  plVar5 = (long *)CONCAT71(in_register_00000011,param_3);
  *(undefined8 *)CONCAT71(in_register_00000011,param_3) = 0;
  plVar4 = *(long **)(CONCAT71(in_register_00000011,param_3) + 8);
  *(undefined8 *)(CONCAT71(in_register_00000011,param_3) + 8) = 0;
  if (plVar4 != (long *)0x0) {
    LOCK();
    plVar1 = plVar4 + 1;
    lVar3 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar3 == 0) {
      (**(code **)(*plVar4 + 0x10))(plVar4);
      std::__shared_weak_count::__release_weak();
    }
  }
  iVar7 = ATCAircraft::GetStatus((ATCAircraft *)param_2);
  cVar10 = '\x01';
  if (iVar7 != 0) {
    return '\x01';
  }
  cVar6 = ATCUtilsAcfIsFlying((ATCAircraft *)param_2);
  if (cVar6 == '\0') {
    return '\x01';
  }
  cVar6 = (**(code **)(*(long *)param_2 + 0x438))(param_2);
  if (cVar6 == '\0') {
    fVar2 = *(float *)(param_2 + 0x1dc);
    if (0.0 < fVar2) {
      if (fVar2 != DAT_02536f24) {
        return '\x01';
      }
      if (NAN(fVar2) || NAN(DAT_02536f24)) {
        return '\x01';
      }
    }
    piVar8 = (int *)ATCAircraft::GetCurrentSegment((ATCAircraft *)param_2);
    if (piVar8 != (int *)0x0) {
      if (*piVar8 == 4) {
        if (*(int *)(param_2 + 0x38) == 0) {
          return '\x01';
        }
      }
      else {
        if (*piVar8 != 7) {
          return '\x01';
        }
        if (piVar8[2] != 1) {
          return '\x01';
        }
      }
    }
    if (*(int *)(param_1 + 0x80) - 5U < 2) {
      pAVar9 = *(ATCAircraft **)(param_2 + 0x2d8);
      lVar3 = *(long *)(param_2 + 0x2e0);
      if (lVar3 != 0) {
        LOCK();
        *(long *)(lVar3 + 8) = *(long *)(lVar3 + 8) + 1;
        UNLOCK();
      }
      *plVar5 = (long)pAVar9;
      plVar4 = (long *)plVar5[1];
      plVar5[1] = lVar3;
      if (plVar4 != (long *)0x0) {
        LOCK();
        plVar1 = plVar4 + 1;
        lVar3 = *plVar1;
        *plVar1 = *plVar1 + -1;
        UNLOCK();
        if (lVar3 == 0) {
          (**(code **)(*plVar4 + 0x10))(plVar4);
          std::__shared_weak_count::__release_weak();
        }
        pAVar9 = (ATCAircraft *)*plVar5;
      }
      cVar10 = (pAVar9 != param_1 && pAVar9 != (ATCAircraft *)0x0) * '\x02';
    }
    return cVar10;
  }
  return '\x01';
}


// 0016f9c0  ATCTaskRequestFlightFollowing::ATCTaskRequestFlightFollowing

/* ATCTaskRequestFlightFollowing::ATCTaskRequestFlightFollowing(std::shared_ptr<ATCController>,
   ATCAircraft*, float) */

void __thiscall
ATCTaskRequestFlightFollowing::ATCTaskRequestFlightFollowing
          (ATCTaskRequestFlightFollowing *this,undefined8 *param_2,undefined8 param_3)

{
  long *plVar1;
  long lVar2;
  undefined8 local_40;
  long *local_38;
  byte local_30;
  char local_2f [4];
  char acStack_2b [4];
  char acStack_27 [4];
  undefined2 uStack_23;
  undefined1 uStack_21;
  undefined1 uStack_20;
  undefined6 uStack_1f;
  undefined1 uStack_19;
  
  local_40 = *param_2;
  local_38 = (long *)param_2[1];
  if (local_38 != (long *)0x0) {
    LOCK();
    local_38[1] = local_38[1] + 1;
    UNLOCK();
  }
  local_30 = 0x2c;
  local_2f[0] = s_RequestFlightFollowing_027ca9eb[0];
  local_2f[1] = s_RequestFlightFollowing_027ca9eb[1];
  local_2f[2] = s_RequestFlightFollowing_027ca9eb[2];
  local_2f[3] = s_RequestFlightFollowing_027ca9eb[3];
  acStack_2b[0] = s_RequestFlightFollowing_027ca9eb[4];
  acStack_2b[1] = s_RequestFlightFollowing_027ca9eb[5];
  acStack_2b[2] = s_RequestFlightFollowing_027ca9eb[6];
  acStack_2b[3] = s_RequestFlightFollowing_027ca9eb[7];
  acStack_27[0] = s_RequestFlightFollowing_027ca9eb[8];
  acStack_27[1] = s_RequestFlightFollowing_027ca9eb[9];
  acStack_27[2] = s_RequestFlightFollowing_027ca9eb[10];
  acStack_27[3] = s_RequestFlightFollowing_027ca9eb[0xb];
  uStack_23 = (undefined2)s_RequestFlightFollowing_027ca9eb._12_4_;
  uStack_21 = 0x6f;
  uStack_20 = 0x6c;
  uStack_1f = 0x676e69776f6c;
  uStack_19 = 0;
  ATCAircraftResponseTask::ATCAircraftResponseTask
            ((ATCAircraftResponseTask *)this,&local_40,param_3,0,&local_30);
  if ((local_30 & 1) != 0) {
    operator_delete((void *)CONCAT17(uStack_19,CONCAT61(uStack_1f,uStack_20)));
  }
  if (local_38 != (long *)0x0) {
    LOCK();
    plVar1 = local_38 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*local_38 + 0x10))(local_38);
      std::__shared_weak_count::__release_weak();
    }
  }
  *(undefined ***)this = &PTR__ATCTaskRequestFlightFollowing_02acc760;
  return;
}


// 0016fa90  ATCTaskRequestFlightFollowing::RunTask

/* ATCTaskRequestFlightFollowing::RunTask(bool) */

undefined4 ATCTaskRequestFlightFollowing::RunTask(bool param_1)

{
  long lVar1;
  long *plVar2;
  ATCAircraft *pAVar3;
  undefined7 in_register_00000039;
  long *plVar4;
  ATCController *this;
  
  plVar4 = (long *)CONCAT71(in_register_00000039,param_1);
  if (plVar4[9] != 0) {
    plVar2 = (long *)std::__shared_weak_count::lock();
    if (plVar2 != (long *)0x0) {
      this = (ATCController *)plVar4[8];
      goto LAB_0016fabf;
    }
  }
  this = (ATCController *)0x0;
  plVar2 = (long *)0x0;
LAB_0016fabf:
  pAVar3 = (ATCAircraft *)(**(code **)(*plVar4 + 0x40))(plVar4);
  ATCController::HandleRequestFlightFollowing(this,pAVar3);
  if (plVar2 != (long *)0x0) {
    LOCK();
    plVar4 = plVar2 + 1;
    lVar1 = *plVar4;
    *plVar4 = *plVar4 + -1;
    UNLOCK();
    if (lVar1 == 0) {
      (**(code **)(*plVar2 + 0x10))(plVar2);
      std::__shared_weak_count::__release_weak();
    }
  }
  return DAT_025246d0;
}


// 0016fb30  ATCController::HandleRequestFlightFollowing

/* ATCController::HandleRequestFlightFollowing(ATCAircraft*) */

undefined8 __thiscall
ATCController::HandleRequestFlightFollowing(ATCController *this,ATCAircraft *param_1)

{
  long *plVar1;
  long lVar2;
  long lVar3;
  code *pcVar4;
  undefined4 uVar5;
  char cVar6;
  undefined8 uVar7;
  ulong uVar8;
  ATCController *this_00;
  long *plVar9;
  ATCTxon local_208 [336];
  undefined8 local_b8;
  undefined8 uStack_b0;
  undefined4 local_a8;
  ATCController *local_98;
  long *local_90;
  ATCController *local_88;
  long *local_80;
  ATCController *local_78;
  long *plStack_70;
  undefined4 local_68;
  ATCController *local_58;
  long *local_50;
  undefined8 local_48;
  long *local_40;
  ATCController *local_38;
  
  local_48 = *(undefined8 *)(this + 0x40);
  if (*(long *)(this + 0x48) == 0) {
    local_40 = (long *)0x0;
LAB_0016fe65:
    std::__throw_bad_weak_ptr();
                    /* WARNING: Does not return */
    pcVar4 = (code *)invalidInstructionException();
    (*pcVar4)();
  }
  local_40 = (long *)std::__shared_weak_count::lock();
  if (local_40 == (long *)0x0) goto LAB_0016fe65;
  ::ATCTxon::ATCTxon(local_208,&local_48,param_1);
  if (local_40 != (long *)0x0) {
    LOCK();
    plVar9 = local_40 + 1;
    lVar2 = *plVar9;
    *plVar9 = *plVar9 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*local_40 + 0x10))(local_40);
      std::__shared_weak_count::__release_weak();
    }
  }
  lVar2 = *(long *)(param_1 + 0x2d8);
  plVar9 = *(long **)(param_1 + 0x2e0);
  if (plVar9 == (long *)0x0) {
LAB_0016fbdd:
    if (lVar2 != 0) goto LAB_0016fbe6;
LAB_0016fc74:
    ATCControllerDb::FindControllerForAirspace((ATCAircraft *)&local_78);
    plVar9 = plStack_70;
    this_00 = local_78;
    if (local_78 != this) {
      local_78 = (ATCController *)0x0;
      plStack_70 = (long *)0x0;
      local_68 = 0;
      local_b8 = 0;
      uStack_b0 = 0;
      local_a8 = 0;
      ATCAircraft::GetPredictedActualPositionAtT(param_1,DAT_02536f28,(GeoPoint3D *)&local_78);
      ATCAircraft::GetPredictedActualPositionAtT(param_1,DAT_02520bc0,(GeoPoint3D *)&local_b8);
      ATCControllerDb::FindControllerForGeoPt
                ((GeoPoint3D *)&local_88,SUB81(_gControllerDb,0),SUB81(&local_78,0));
      if (local_88 == this) {
        local_38 = this_00;
        uVar7 = 0;
        ATCControllerDb::FindControllerForGeoPt
                  ((GeoPoint3D *)&local_98,SUB81(_gControllerDb,0),SUB81(&local_b8,0));
        uVar8 = CONCAT71((int7)((ulong)uVar7 >> 8),local_98 == this);
        if (local_90 != (long *)0x0) {
          LOCK();
          plVar1 = local_90 + 1;
          lVar2 = *plVar1;
          *plVar1 = *plVar1 + -1;
          UNLOCK();
          if (lVar2 == 0) {
            uVar8 = uVar8 & 0xffffffff;
            (**(code **)(*local_90 + 0x10))(local_90);
            std::__shared_weak_count::__release_weak();
          }
        }
        this_00 = local_38;
        if (local_80 != (long *)0x0) goto LAB_0016fd77;
LAB_0016fd89:
        cVar6 = (char)uVar8;
      }
      else {
        uVar8 = 0;
        if (local_80 == (long *)0x0) goto LAB_0016fd89;
LAB_0016fd77:
        LOCK();
        plVar1 = local_80 + 1;
        lVar2 = *plVar1;
        *plVar1 = *plVar1 + -1;
        UNLOCK();
        if (lVar2 != 0) goto LAB_0016fd89;
        local_38 = (ATCController *)CONCAT44(local_38._4_4_,(int)uVar8);
        (**(code **)(*local_80 + 0x10))(local_80);
        std::__shared_weak_count::__release_weak();
        cVar6 = (char)local_38;
      }
      if (cVar6 != '\0') {
        if (plVar9 != (long *)0x0) {
          LOCK();
          plVar1 = plVar9 + 1;
          lVar2 = *plVar1;
          *plVar1 = *plVar1 + -1;
          UNLOCK();
          if (lVar2 == 0) {
            (**(code **)(*plVar9 + 0x10))(plVar9);
            std::__shared_weak_count::__release_weak();
          }
        }
        goto LAB_0016fbe6;
      }
      if (this_00 != (ATCController *)0x0) {
        ::ATCTxon::NotInMyAirspace(local_208);
        local_50 = plVar9;
        if (plVar9 != (long *)0x0) {
          LOCK();
          plVar9[1] = plVar9[1] + 1;
          UNLOCK();
        }
        local_58 = this_00;
        uVar5 = GetChanWithSpace(this_00);
        ::ATCTxon::ContactController(local_208,&local_58,uVar5,1);
        if (local_50 != (long *)0x0) {
          LOCK();
          plVar1 = local_50 + 1;
          lVar2 = *plVar1;
          *plVar1 = *plVar1 + -1;
          UNLOCK();
          if (lVar2 == 0) {
            (**(code **)(*local_50 + 0x10))(local_50);
            std::__shared_weak_count::__release_weak();
          }
        }
        goto LAB_0016fbfb;
      }
    }
  }
  else {
    LOCK();
    plVar9[1] = plVar9[1] + 1;
    UNLOCK();
    LOCK();
    plVar1 = plVar9 + 1;
    lVar3 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar3 != 0) goto LAB_0016fbdd;
    (**(code **)(*plVar9 + 0x10))(plVar9);
    std::__shared_weak_count::__release_weak();
    if (lVar2 == 0) goto LAB_0016fc74;
LAB_0016fbe6:
    plVar9 = (long *)0x0;
  }
  SetFlightFollowing(this,param_1,local_208);
LAB_0016fbfb:
  CreateTxon(this,param_1,local_208,0);
  ::ATCTxon::~ATCTxon(local_208);
  if (plVar9 != (long *)0x0) {
    LOCK();
    plVar1 = plVar9 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar9 + 0x10))(plVar9);
      std::__shared_weak_count::__release_weak();
    }
  }
  return 0xffffffff;
}


// 0016ff40  ATCController::SetFlightFollowing

/* ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&) */

void __thiscall
ATCController::SetFlightFollowing(ATCController *this,ATCAircraft *param_1,ATCTxon *param_2)

{
  ushort uVar1;
  char cVar2;
  bool bVar3;
  undefined4 uVar4;
  undefined ***pppuVar5;
  undefined **local_98;
  uint local_90;
  undefined ***local_78;
  undefined **local_68 [4];
  undefined ***local_48;
  long local_30;
  
  local_30 = *(long *)PTR____stack_chk_guard_02ac0540;
  cVar2 = IsOurAircraft(this,param_1);
  if (cVar2 == '\0') {
    bVar3 = (bool)(**(code **)(*(long *)param_1 + 0x388))(param_1,1);
    AcceptOwnership<int>((ATCAircraft *)this,(int)param_1,bVar3);
  }
  param_2[0x11] = *(ATCTxon *)(param_1 + 0x28);
  ATCAircraft::GetPredictedFutureCourse();
  ATCRouteUtils::SetRouteToVFRNav((ATCRouteUtils *)param_1);
  uVar4 = *(undefined4 *)(this + 0x1f0);
  (**(code **)(*(long *)param_1 + 0x40))
            (*(undefined4 *)(this + 0x1f0),param_1,
             *(undefined4 *)(_vec_atc + 0x88 + (long)*(int *)(this + 0x1c8) * 0xa0));
  if (*(int *)(param_1 + 0x38) < 5) {
    cVar2 = IsValidTxdrCode(*(ushort *)(param_1 + 0x1c0));
    if (cVar2 == '\0') {
      AssignNewTxdrCode(this,param_1,false);
    }
    uVar1 = *(ushort *)(param_1 + 0x1c0);
    uVar4 = ATCUtilsGetRoundedPressure
                      (uVar4,*(undefined4 *)(_vec_atc + 0x88 + (long)*(int *)(this + 0x1c8) * 0xa0))
    ;
    local_98 = &PTR____func_02acf858;
    local_90 = (uint)uVar1;
    local_78 = &local_98;
    ::ATCTxon::AcknowledgeFlightFollowing
              (param_2,local_90,uVar4,
               *(undefined4 *)(_vec_atc + 0x88 + (long)*(int *)(this + 0x1c8) * 0xa0),&local_98);
    pppuVar5 = local_78;
    if (&local_98 != local_78) goto LAB_0017010c;
  }
  else {
    uVar4 = ATCUtilsGetRoundedPressure
                      (uVar4,*(undefined4 *)(_vec_atc + 0x88 + (long)*(int *)(this + 0x1c8) * 0xa0))
    ;
    local_68[0] = &PTR____func_02acf7d8;
    local_48 = local_68;
    ::ATCTxon::HaveDetails
              (param_2,uVar4,*(undefined4 *)(_vec_atc + 0x88 + (long)*(int *)(this + 0x1c8) * 0xa0),
               local_68);
    pppuVar5 = local_48;
    if (local_68 != local_48) {
LAB_0017010c:
      if (pppuVar5 != (undefined ***)0x0) {
        (*(code *)(*pppuVar5)[5])();
      }
      goto LAB_00170117;
    }
  }
  (*(code *)(*pppuVar5)[4])();
LAB_00170117:
  if (*(long *)PTR____stack_chk_guard_02ac0540 == local_30) {
    return;
  }
                    /* WARNING: Subroutine does not return */
  ___stack_chk_fail();
}


// 001909d0  ATCPilotMenuItemCancelFlightFollowing::IsCommandReady

/* ATCPilotMenuItemCancelFlightFollowing::IsCommandReady(ATCAircraft*, ATCController*) const */

char __thiscall
ATCPilotMenuItemCancelFlightFollowing::IsCommandReady
          (ATCPilotMenuItemCancelFlightFollowing *this,ATCAircraft *param_1,ATCController *param_2)

{
  long *plVar1;
  long lVar2;
  ATCController *pAVar3;
  long *plVar4;
  char cVar5;
  char cVar6;
  
  if (param_2 == (ATCController *)0x0) {
    cVar6 = '\x02';
  }
  else {
    cVar6 = '\x01';
    if ((((*(long *)(param_1 + 0x270) == 0) &&
         (cVar5 = ATCAircraft::IsVFRFlightFollowing(param_1), cVar5 != '\0')) &&
        (4 < *(int *)(param_2 + 0x80))) && (*(float *)(param_1 + 0x1dc) <= 0.0)) {
      pAVar3 = *(ATCController **)(param_1 + 0x2d8);
      plVar4 = *(long **)(param_1 + 0x2e0);
      if (plVar4 == (long *)0x0) {
        cVar6 = '\x02';
        if (pAVar3 != (ATCController *)0x0) {
          cVar6 = (pAVar3 != param_2) * '\x02';
        }
      }
      else {
        LOCK();
        plVar4[1] = plVar4[1] + 1;
        UNLOCK();
        cVar6 = '\x02';
        if (pAVar3 != (ATCController *)0x0) {
          cVar6 = (pAVar3 != param_2) * '\x02';
        }
        LOCK();
        plVar1 = plVar4 + 1;
        lVar2 = *plVar1;
        *plVar1 = *plVar1 + -1;
        UNLOCK();
        if (lVar2 == 0) {
          (**(code **)(*plVar4 + 0x10))(plVar4);
          std::__shared_weak_count::__release_weak();
        }
      }
    }
  }
  return cVar6;
}


// 00190ab0  ATCController::CmdCancelFlightFollowing

/* ATCController::CmdCancelFlightFollowing(ATCAircraft*, std::shared_ptr<ATCController>&, bool,
   std::vector<std::pair<ATCPilotMenuParameter::eOptionType, ATCPilotMenuParameter::ChoiceData>,
   std::allocator<std::pair<ATCPilotMenuParameter::eOptionType, ATCPilotMenuParameter::ChoiceData> >
   > const&) */

ATCController * __thiscall
ATCController::CmdCancelFlightFollowing
          (ATCController *this,ATCAircraft *param_1,shared_ptr *param_2,bool param_3,vector *param_4
          )

{
  long *plVar1;
  shared_ptr *psVar2;
  long lVar3;
  undefined8 uVar4;
  char cVar5;
  int iVar6;
  ATCAircraft *pAVar7;
  long *plVar8;
  long *plVar9;
  _Unwind_Exception *exception_object;
  undefined7 in_register_00000009;
  __shared_weak_count *this_00;
  vector *pvVar10;
  bool extraout_DL;
  shared_ptr *psVar11;
  undefined8 local_48;
  long *local_40;
  undefined8 local_38;
  
  this_00 = (__shared_weak_count *)CONCAT71(in_register_00000009,param_3);
  local_38 = CONCAT44(local_38._4_4_,(int)param_4);
  *(undefined8 *)this_00 = 0;
  plVar8 = *(long **)(this_00 + 8);
  *(undefined8 *)(this_00 + 8) = 0;
  if (plVar8 != (long *)0x0) {
    LOCK();
    plVar1 = plVar8 + 1;
    lVar3 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar3 == 0) {
      (**(code **)(*plVar8 + 0x10))(plVar8);
      std::__shared_weak_count::__release_weak();
      cVar5 = ATCAircraft::IsVFRFlightFollowing((ATCAircraft *)param_2);
      goto joined_r0x00190b09;
    }
  }
  cVar5 = ATCAircraft::IsVFRFlightFollowing((ATCAircraft *)param_2);
joined_r0x00190b09:
  if (((cVar5 == '\0') || (*(int *)(param_1 + 0x80) < 5)) || (0.0 < *(float *)(param_2 + 0x1dc))) {
    *(undefined4 *)this = 1;
  }
  else {
    pAVar7 = *(ATCAircraft **)(param_2 + 0x2d8);
    pvVar10 = *(vector **)(param_2 + 0x2e0);
    if (pvVar10 != (vector *)0x0) {
      LOCK();
      *(long *)(pvVar10 + 8) = *(long *)(pvVar10 + 8) + 1;
      UNLOCK();
    }
    *(ATCAircraft **)this_00 = pAVar7;
    plVar8 = *(long **)(this_00 + 8);
    *(vector **)(this_00 + 8) = pvVar10;
    if (plVar8 != (long *)0x0) {
      LOCK();
      plVar1 = plVar8 + 1;
      lVar3 = *plVar1;
      *plVar1 = *plVar1 + -1;
      UNLOCK();
      if (lVar3 == 0) {
        (**(code **)(*plVar8 + 0x10))(plVar8);
        std::__shared_weak_count::__release_weak();
      }
      pAVar7 = *(ATCAircraft **)this_00;
    }
    if ((pAVar7 == (ATCAircraft *)0x0) || (pAVar7 != param_1)) {
      *(undefined4 *)this = 2;
    }
    else {
      if ((char)local_38 == '\0') {
        psVar11 = (shared_ptr *)0x0;
        iVar6 = (**(code **)(*(long *)param_2 + 0x388))(param_2);
        if (iVar6 != 0) {
          if (*(long *)(param_1 + 0x48) != 0) {
            uVar4 = *(undefined8 *)(param_1 + 0x40);
            plVar8 = (long *)std::__shared_weak_count::lock();
            if (plVar8 != (long *)0x0) {
              local_38 = uVar4;
              plVar9 = operator_new(0x80);
              plVar9[1] = 0;
              plVar9[2] = 0;
              *plVar9 = (long)&PTR____shared_ptr_emplace_02ad05d8;
              local_48 = local_38;
              local_40 = plVar8;
              ATCTaskCancelFlightFollowing::ATCTaskCancelFlightFollowing
                        ((ATCTaskCancelFlightFollowing *)(float)DAT_0315d538,plVar9 + 3,&local_48,
                         param_2);
              LOCK();
              plVar1 = plVar8 + 1;
              lVar3 = *plVar1;
              *plVar1 = *plVar1 + -1;
              UNLOCK();
              if (lVar3 == 0) {
                (**(code **)(*plVar8 + 0x10))(plVar8);
                std::__shared_weak_count::__release_weak();
              }
              *(undefined4 *)this = 0;
              *(long **)(this + 8) = plVar9 + 3;
              *(long **)(this + 0x10) = plVar9;
              LOCK();
              plVar9[1] = plVar9[1] + 1;
              UNLOCK();
              LOCK();
              plVar8 = plVar9 + 1;
              lVar3 = *plVar8;
              *plVar8 = *plVar8 + -1;
              UNLOCK();
              if (lVar3 == 0) {
                (**(code **)(*plVar9 + 0x10))(plVar9);
                std::__shared_weak_count::__release_weak();
                return this;
              }
              return this;
            }
          }
          exception_object = (_Unwind_Exception *)std::__throw_bad_weak_ptr();
          LOCK();
          psVar2 = param_2 + 8;
          lVar3 = *(long *)psVar2;
          *(long *)psVar2 = *(long *)psVar2 + -1;
          UNLOCK();
          if (lVar3 == 0) {
            CmdCancelFlightFollowing((ATCAircraft *)param_2,psVar11,extraout_DL,pvVar10);
          }
          std::__shared_weak_count::~__shared_weak_count(this_00);
          operator_delete(this_00);
                    /* WARNING: Subroutine does not return */
          __Unwind_Resume(exception_object);
        }
      }
      *(undefined4 *)this = 0;
    }
  }
  *(undefined8 *)(this + 8) = 0;
  *(undefined8 *)(this + 0x10) = 0;
  return this;
}


// 00190d50  ATCPilotMenuItemCancelFlightFollowing::DoCommand

/* ATCPilotMenuItemCancelFlightFollowing::DoCommand(ATCController*, std::vector<int,
   std::allocator<int> > const&) const */

int ATCPilotMenuItemCancelFlightFollowing::DoCommand(ATCController *param_1,vector *param_2)

{
  void *pvVar1;
  vector *pvVar2;
  void *pvVar3;
  int iVar4;
  void *local_48;
  void *local_40;
  
  pvVar2 = _gUsersAircraft;
  iVar4 = 1;
  if ((param_2 != (vector *)0x0) && (_gUsersAircraft != (vector *)0x0)) {
    ATCPilotMenuItem::GetChosenItems((vector *)&local_48);
    iVar4 = ATCAircraft::PilotCmdCancelFlightFollowing(pvVar2);
    pvVar3 = local_48;
    if (local_48 != (void *)0x0) {
      while (pvVar1 = local_40, pvVar1 != pvVar3) {
        local_40 = (void *)((long)pvVar1 + -0x28);
        if ((*(byte *)((long)pvVar1 + -0x20) & 1) != 0) {
          operator_delete(*(void **)((long)pvVar1 + -0x10));
        }
      }
      local_40 = pvVar3;
      operator_delete(local_48);
    }
    if (iVar4 == 3) {
      ATCController::SilenceAircraft((ATCController *)param_2,(ATCAircraft *)_gUsersAircraft);
      iVar4 = 3;
    }
  }
  return iVar4;
}


// 00190e40  ATCAircraft::PilotCmdCancelFlightFollowing

/* ATCAircraft::PilotCmdCancelFlightFollowing(std::vector<std::pair<ATCPilotMenuParameter::eOptionType,
   ATCPilotMenuParameter::ChoiceData>, std::allocator<std::pair<ATCPilotMenuParameter::eOptionType,
   ATCPilotMenuParameter::ChoiceData> > > const&) */

int ATCAircraft::PilotCmdCancelFlightFollowing(vector *param_1)

{
  __tree_node *p_Var1;
  long *plVar2;
  long lVar3;
  ATCRadio *this;
  int iVar4;
  char cVar5;
  int iVar6;
  undefined4 uVar7;
  float fVar8;
  int local_1d0 [2];
  undefined4 local_1c8;
  undefined4 uStack_1c4;
  undefined4 uStack_1c0;
  undefined4 uStack_1bc;
  int local_7c;
  undefined8 local_78;
  undefined8 uStack_70;
  ATCAircraft *local_68;
  long *local_60;
  __tree_node *local_58;
  __tree_node *p_Stack_50;
  undefined8 local_48;
  int local_34;
  
  ATCControllerDb::FindListeningController((ATCAircraft *)&local_68,SUB81(_gControllerDb,0));
  if (local_68 == (ATCAircraft *)0x0) {
    iVar6 = 2;
    goto LAB_00191083;
  }
  if (_gUsersAircraft == param_1) {
    cVar5 = ATCRadio::IsP0Talking(_gRadio,&local_7c);
    iVar6 = 1;
    if (cVar5 != '\0') goto LAB_00191083;
  }
  this = _gRadio;
  local_34 = 3;
  local_78 = 0;
  uStack_70 = (long *)0x0;
  iVar6 = (**(code **)(*(long *)param_1 + 0x388))(param_1,1);
  fVar8 = 0.0;
  if (_gUsersAircraft != param_1) {
    fVar8 = DAT_02520bf0;
  }
  cVar5 = ATCRadio::IsChanOpen(this,(ATCAircraft *)param_1,iVar6,fVar8);
  iVar6 = 3;
  if (cVar5 == '\0') {
LAB_00190f7c:
    if ((iVar6 == 3) && (iVar4 = 3, _gUsersAircraft == param_1)) goto LAB_00190fb9;
  }
  else {
    local_58 = (__tree_node *)0x0;
    p_Stack_50 = (__tree_node *)0x0;
    ATCController::CmdCancelFlightFollowing
              ((ATCController *)local_1d0,local_68,(shared_ptr *)param_1,SUB81(&local_58,0),
               (vector *)0x0);
    local_34 = local_1d0[0];
    local_78 = CONCAT44(uStack_1c4,local_1c8);
    uStack_70 = (long *)CONCAT44(uStack_1bc,uStack_1c0);
    if (local_1d0[0] != 0) {
      log_request_failure((ATCAircraft *)param_1,param_1,&local_68,&local_58,local_1d0[0],
                          "RequestCancelFlightFollowing");
    }
    iVar6 = local_34;
    if (p_Stack_50 != (__tree_node *)0x0) {
      LOCK();
      p_Var1 = p_Stack_50 + 8;
      lVar3 = *(long *)p_Var1;
      *(long *)p_Var1 = *(long *)p_Var1 + -1;
      UNLOCK();
      if (lVar3 == 0) {
        (**(code **)(*(long *)p_Stack_50 + 0x10))(p_Stack_50);
        std::__shared_weak_count::__release_weak();
        iVar6 = local_34;
      }
    }
    local_34 = iVar6;
    if (iVar6 != 0) goto LAB_00190f7c;
    iVar4 = 0;
LAB_00190fb9:
    iVar6 = iVar4;
    ::ATCTxon::ATCTxon((ATCTxon *)local_1d0,(ATCAircraft *)param_1,(shared_ptr *)&local_68,
                       (shared_ptr *)&local_78,false);
    ::ATCTxon::RequestCancelFlightFollowing((ATCTxon *)local_1d0);
    uVar7 = (**(code **)(*(long *)param_1 + 0x388))(param_1,1);
    local_58 = operator_new(0x20);
    *(undefined4 *)(local_58 + 0x1c) = uVar7;
    *(undefined8 *)local_58 = 0;
    *(undefined8 *)(local_58 + 8) = 0;
    *(__tree_node ***)(local_58 + 0x10) = &p_Stack_50;
    local_58[0x18] = (__tree_node)0x1;
    local_48 = 1;
    p_Stack_50 = local_58;
    ATCRadio::Transmit((set *)_gRadio,(ATCTxon *)&local_58);
    std::__tree<int,std::less<int>,std::allocator<int>>::destroy
              ((__tree<int,std::less<int>,std::allocator<int>> *)&local_58,p_Stack_50);
    ::ATCTxon::~ATCTxon((ATCTxon *)local_1d0);
  }
  if (uStack_70 != (long *)0x0) {
    LOCK();
    plVar2 = uStack_70 + 1;
    lVar3 = *plVar2;
    *plVar2 = *plVar2 + -1;
    UNLOCK();
    if (lVar3 == 0) {
      (**(code **)(*uStack_70 + 0x10))(uStack_70);
      std::__shared_weak_count::__release_weak();
    }
  }
LAB_00191083:
  if (local_60 != (long *)0x0) {
    LOCK();
    plVar2 = local_60 + 1;
    lVar3 = *plVar2;
    *plVar2 = *plVar2 + -1;
    UNLOCK();
    if (lVar3 == 0) {
      (**(code **)(*local_60 + 0x10))(local_60);
      std::__shared_weak_count::__release_weak();
    }
  }
  return iVar6;
}


// 00191190  ATCPilotMenuItemCancelFlightFollowing::IsSubItemValid

/* ATCPilotMenuItemCancelFlightFollowing::IsSubItemValid(ATCController*, ATCPilotMenuParameter
   const&, std::vector<ATCPilotMenuParameter const*, std::allocator<ATCPilotMenuParameter const*> >
   const&) const */

undefined1
ATCPilotMenuItemCancelFlightFollowing::IsSubItemValid
          (ATCController *param_1,ATCPilotMenuParameter *param_2,vector *param_3)

{
  return 1;
}


// 001911a0  ATCTaskCancelFlightFollowing::ATCTaskCancelFlightFollowing

/* ATCTaskCancelFlightFollowing::ATCTaskCancelFlightFollowing(std::shared_ptr<ATCController>,
   ATCAircraft*, float) */

void __thiscall
ATCTaskCancelFlightFollowing::ATCTaskCancelFlightFollowing
          (ATCTaskCancelFlightFollowing *this,undefined8 *param_2,undefined8 param_3)

{
  long *plVar1;
  long lVar2;
  undefined8 local_40;
  long *local_38;
  byte local_30;
  char local_2f [4];
  char acStack_2b [4];
  char acStack_27 [4];
  char cStack_23;
  undefined2 uStack_22;
  undefined1 uStack_20;
  undefined5 uStack_1f;
  undefined1 uStack_1a;
  undefined1 uStack_19;
  
  local_40 = *param_2;
  local_38 = (long *)param_2[1];
  if (local_38 != (long *)0x0) {
    LOCK();
    local_38[1] = local_38[1] + 1;
    UNLOCK();
  }
  local_30 = 0x2a;
  local_2f[0] = s_CancelFlightFollowing_027cae0d[0];
  local_2f[1] = s_CancelFlightFollowing_027cae0d[1];
  local_2f[2] = s_CancelFlightFollowing_027cae0d[2];
  local_2f[3] = s_CancelFlightFollowing_027cae0d[3];
  acStack_2b[0] = s_CancelFlightFollowing_027cae0d[4];
  acStack_2b[1] = s_CancelFlightFollowing_027cae0d[5];
  acStack_2b[2] = s_CancelFlightFollowing_027cae0d[6];
  acStack_2b[3] = s_CancelFlightFollowing_027cae0d[7];
  acStack_27[0] = s_CancelFlightFollowing_027cae0d[8];
  acStack_27[1] = s_CancelFlightFollowing_027cae0d[9];
  acStack_27[2] = s_CancelFlightFollowing_027cae0d[10];
  acStack_27[3] = s_CancelFlightFollowing_027cae0d[0xb];
  cStack_23 = (char)s_CancelFlightFollowing_027cae0d._12_4_;
  uStack_22 = 0x6c6f;
  uStack_20 = 0x6c;
  uStack_1f = 0x676e69776f;
  uStack_1a = 0;
  ATCAircraftResponseTask::ATCAircraftResponseTask
            ((ATCAircraftResponseTask *)this,&local_40,param_3,0,&local_30);
  if ((local_30 & 1) != 0) {
    operator_delete((void *)CONCAT17(uStack_19,CONCAT16(uStack_1a,CONCAT51(uStack_1f,uStack_20))));
  }
  if (local_38 != (long *)0x0) {
    LOCK();
    plVar1 = local_38 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*local_38 + 0x10))(local_38);
      std::__shared_weak_count::__release_weak();
    }
  }
  *(undefined ***)this = &PTR__ATCTaskCancelFlightFollowing_02acd000;
  return;
}


// 00191270  ATCTaskCancelFlightFollowing::GetTaskPriority

/* ATCTaskCancelFlightFollowing::GetTaskPriority() const */

char __thiscall ATCTaskCancelFlightFollowing::GetTaskPriority(ATCTaskCancelFlightFollowing *this)

{
  long lVar1;
  
  lVar1 = (**(code **)(*(long *)this + 0x40))();
  return (lVar1 != _gP0Aircraft) * '\x05' + 'T';
}


// 001912a0  ATCTaskCancelFlightFollowing::RunTask

/* ATCTaskCancelFlightFollowing::RunTask(bool) */

undefined4 ATCTaskCancelFlightFollowing::RunTask(bool param_1)

{
  long lVar1;
  long *plVar2;
  ATCAircraft *pAVar3;
  undefined7 in_register_00000039;
  long *plVar4;
  ATCController *this;
  
  plVar4 = (long *)CONCAT71(in_register_00000039,param_1);
  if (plVar4[9] != 0) {
    plVar2 = (long *)std::__shared_weak_count::lock();
    if (plVar2 != (long *)0x0) {
      this = (ATCController *)plVar4[8];
      goto LAB_001912cf;
    }
  }
  this = (ATCController *)0x0;
  plVar2 = (long *)0x0;
LAB_001912cf:
  pAVar3 = (ATCAircraft *)(**(code **)(*plVar4 + 0x40))(plVar4);
  ATCController::HandleCancelFlightFollowing(this,pAVar3);
  if (plVar2 != (long *)0x0) {
    LOCK();
    plVar4 = plVar2 + 1;
    lVar1 = *plVar4;
    *plVar4 = *plVar4 + -1;
    UNLOCK();
    if (lVar1 == 0) {
      (**(code **)(*plVar2 + 0x10))(plVar2);
      std::__shared_weak_count::__release_weak();
    }
  }
  return DAT_025246d0;
}


// 00191340  ATCController::HandleCancelFlightFollowing

/* ATCController::HandleCancelFlightFollowing(ATCAircraft*) */

undefined8 __thiscall
ATCController::HandleCancelFlightFollowing(ATCController *this,ATCAircraft *param_1)

{
  long *plVar1;
  long lVar2;
  char cVar3;
  _Unwind_Exception *exception_object;
  undefined ***unaff_R15;
  ATCTxon local_1b8 [336];
  undefined8 local_68;
  long *local_60;
  undefined **local_58;
  undefined2 local_50;
  undefined ***local_38;
  long local_28;
  
  local_28 = *(long *)PTR____stack_chk_guard_02ac0540;
  cVar3 = ATCAircraft::IsVFRFlightFollowing(param_1);
  if (cVar3 != '\0') {
    cVar3 = IsOurAircraft(this,param_1);
    if (cVar3 != '\0') {
      CancelTxdrCode(this,param_1,false);
      local_68 = *(undefined8 *)(this + 0x40);
      if (*(long *)(this + 0x48) == 0) {
        local_60 = (long *)0x0;
      }
      else {
        local_60 = (long *)std::__shared_weak_count::lock();
        if (local_60 != (long *)0x0) {
          ::ATCTxon::ATCTxon(local_1b8,&local_68,param_1);
          if (local_60 != (long *)0x0) {
            LOCK();
            plVar1 = local_60 + 1;
            lVar2 = *plVar1;
            *plVar1 = *plVar1 + -1;
            UNLOCK();
            if (lVar2 == 0) {
              (**(code **)(*local_60 + 0x10))(local_60);
              std::__shared_weak_count::__release_weak();
            }
          }
          local_50 = *(undefined2 *)(param_1 + 0x1c0);
          local_58 = &PTR____func_02ad0628;
          local_38 = &local_58;
          ::ATCTxon::FlightFollowingCancelled(local_1b8,local_50,&local_58);
          if (&local_58 == local_38) {
            (*(code *)(*local_38)[4])();
          }
          else if (local_38 != (undefined ***)0x0) {
            (*(code *)(*local_38)[5])();
          }
          ::ATCTxon::ResumeOwnNav(local_1b8);
          CreateTxon(this,param_1,local_1b8,1);
          DropAircraft(this,param_1,false);
          ::ATCTxon::~ATCTxon(local_1b8);
          goto LAB_0019147f;
        }
      }
      exception_object = (_Unwind_Exception *)std::__throw_bad_weak_ptr();
      if (unaff_R15 == local_38) {
        (*(code *)(*local_38)[4])();
      }
      else if (local_38 != (undefined ***)0x0) {
        (*(code *)(*local_38)[5])();
      }
      ::ATCTxon::~ATCTxon(local_1b8);
                    /* WARNING: Subroutine does not return */
      __Unwind_Resume(exception_object);
    }
  }
LAB_0019147f:
  if (*(long *)PTR____stack_chk_guard_02ac0540 == local_28) {
    return 0xffffffff;
  }
                    /* WARNING: Subroutine does not return */
  ___stack_chk_fail();
}


// 0019db40  ATCPilotMenuItemFlightPlanForm::~ATCPilotMenuItemFlightPlanForm

/* ATCPilotMenuItemFlightPlanForm::~ATCPilotMenuItemFlightPlanForm() */

void __thiscall
ATCPilotMenuItemFlightPlanForm::~ATCPilotMenuItemFlightPlanForm
          (ATCPilotMenuItemFlightPlanForm *this)

{
  ATCPilotMenuParameter *pAVar1;
  ATCPilotMenuParameter *pAVar2;
  ATCPilotMenuParameter *pAVar3;
  
  *(undefined ***)this = &PTR__ATCPilotMenuItem_02aceb48;
  if (((byte)this[0x28] & 1) != 0) {
    operator_delete(*(void **)(this + 0x38));
  }
  pAVar1 = *(ATCPilotMenuParameter **)(this + 8);
  if (pAVar1 == (ATCPilotMenuParameter *)0x0) {
    return;
  }
  pAVar2 = *(ATCPilotMenuParameter **)(this + 0x10);
  pAVar3 = pAVar1;
  if (pAVar2 != pAVar1) {
    do {
      pAVar2 = pAVar2 + -0x70;
      std::destroy_at<ATCPilotMenuParameter>(pAVar2);
    } while (pAVar2 != pAVar1);
    pAVar3 = *(ATCPilotMenuParameter **)(this + 8);
  }
  *(ATCPilotMenuParameter **)(this + 0x10) = pAVar1;
  operator_delete(pAVar3);
  return;
}


// 0019dbc0  ATCPilotMenuItemFlightPlanForm::~ATCPilotMenuItemFlightPlanForm

/* ATCPilotMenuItemFlightPlanForm::~ATCPilotMenuItemFlightPlanForm() */

void __thiscall
ATCPilotMenuItemFlightPlanForm::~ATCPilotMenuItemFlightPlanForm
          (ATCPilotMenuItemFlightPlanForm *this)

{
  ATCPilotMenuParameter *pAVar1;
  ATCPilotMenuParameter *pAVar2;
  ATCPilotMenuParameter *pAVar3;
  
  *(undefined ***)this = &PTR__ATCPilotMenuItem_02aceb48;
  if (((byte)this[0x28] & 1) != 0) {
    operator_delete(*(void **)(this + 0x38));
  }
  pAVar1 = *(ATCPilotMenuParameter **)(this + 8);
  if (pAVar1 != (ATCPilotMenuParameter *)0x0) {
    pAVar2 = *(ATCPilotMenuParameter **)(this + 0x10);
    pAVar3 = pAVar1;
    if (pAVar2 != pAVar1) {
      do {
        pAVar2 = pAVar2 + -0x70;
        std::destroy_at<ATCPilotMenuParameter>(pAVar2);
      } while (pAVar2 != pAVar1);
      pAVar3 = *(ATCPilotMenuParameter **)(this + 8);
    }
    *(ATCPilotMenuParameter **)(this + 0x10) = pAVar1;
    operator_delete(pAVar3);
  }
  operator_delete(this);
  return;
}


// 0019e940  ATCPilotMenuItemRequestFlightFollowing::~ATCPilotMenuItemRequestFlightFollowing

/* ATCPilotMenuItemRequestFlightFollowing::~ATCPilotMenuItemRequestFlightFollowing() */

void __thiscall
ATCPilotMenuItemRequestFlightFollowing::~ATCPilotMenuItemRequestFlightFollowing
          (ATCPilotMenuItemRequestFlightFollowing *this)

{
  ATCPilotMenuParameter *pAVar1;
  ATCPilotMenuParameter *pAVar2;
  ATCPilotMenuParameter *pAVar3;
  
  *(undefined ***)this = &PTR__ATCPilotMenuItem_02aceb48;
  if (((byte)this[0x28] & 1) != 0) {
    operator_delete(*(void **)(this + 0x38));
  }
  pAVar1 = *(ATCPilotMenuParameter **)(this + 8);
  if (pAVar1 == (ATCPilotMenuParameter *)0x0) {
    return;
  }
  pAVar2 = *(ATCPilotMenuParameter **)(this + 0x10);
  pAVar3 = pAVar1;
  if (pAVar2 != pAVar1) {
    do {
      pAVar2 = pAVar2 + -0x70;
      std::destroy_at<ATCPilotMenuParameter>(pAVar2);
    } while (pAVar2 != pAVar1);
    pAVar3 = *(ATCPilotMenuParameter **)(this + 8);
  }
  *(ATCPilotMenuParameter **)(this + 0x10) = pAVar1;
  operator_delete(pAVar3);
  return;
}


// 0019e9c0  ATCPilotMenuItemRequestFlightFollowing::~ATCPilotMenuItemRequestFlightFollowing

/* ATCPilotMenuItemRequestFlightFollowing::~ATCPilotMenuItemRequestFlightFollowing() */

void __thiscall
ATCPilotMenuItemRequestFlightFollowing::~ATCPilotMenuItemRequestFlightFollowing
          (ATCPilotMenuItemRequestFlightFollowing *this)

{
  ATCPilotMenuParameter *pAVar1;
  ATCPilotMenuParameter *pAVar2;
  ATCPilotMenuParameter *pAVar3;
  
  *(undefined ***)this = &PTR__ATCPilotMenuItem_02aceb48;
  if (((byte)this[0x28] & 1) != 0) {
    operator_delete(*(void **)(this + 0x38));
  }
  pAVar1 = *(ATCPilotMenuParameter **)(this + 8);
  if (pAVar1 != (ATCPilotMenuParameter *)0x0) {
    pAVar2 = *(ATCPilotMenuParameter **)(this + 0x10);
    pAVar3 = pAVar1;
    if (pAVar2 != pAVar1) {
      do {
        pAVar2 = pAVar2 + -0x70;
        std::destroy_at<ATCPilotMenuParameter>(pAVar2);
      } while (pAVar2 != pAVar1);
      pAVar3 = *(ATCPilotMenuParameter **)(this + 8);
    }
    *(ATCPilotMenuParameter **)(this + 0x10) = pAVar1;
    operator_delete(pAVar3);
  }
  operator_delete(this);
  return;
}


// 0019f440  ATCPilotMenuItemCancelFlightFollowing::~ATCPilotMenuItemCancelFlightFollowing

/* ATCPilotMenuItemCancelFlightFollowing::~ATCPilotMenuItemCancelFlightFollowing() */

void __thiscall
ATCPilotMenuItemCancelFlightFollowing::~ATCPilotMenuItemCancelFlightFollowing
          (ATCPilotMenuItemCancelFlightFollowing *this)

{
  ATCPilotMenuParameter *pAVar1;
  ATCPilotMenuParameter *pAVar2;
  ATCPilotMenuParameter *pAVar3;
  
  *(undefined ***)this = &PTR__ATCPilotMenuItem_02aceb48;
  if (((byte)this[0x28] & 1) != 0) {
    operator_delete(*(void **)(this + 0x38));
  }
  pAVar1 = *(ATCPilotMenuParameter **)(this + 8);
  if (pAVar1 == (ATCPilotMenuParameter *)0x0) {
    return;
  }
  pAVar2 = *(ATCPilotMenuParameter **)(this + 0x10);
  pAVar3 = pAVar1;
  if (pAVar2 != pAVar1) {
    do {
      pAVar2 = pAVar2 + -0x70;
      std::destroy_at<ATCPilotMenuParameter>(pAVar2);
    } while (pAVar2 != pAVar1);
    pAVar3 = *(ATCPilotMenuParameter **)(this + 8);
  }
  *(ATCPilotMenuParameter **)(this + 0x10) = pAVar1;
  operator_delete(pAVar3);
  return;
}


// 0019f4c0  ATCPilotMenuItemCancelFlightFollowing::~ATCPilotMenuItemCancelFlightFollowing

/* ATCPilotMenuItemCancelFlightFollowing::~ATCPilotMenuItemCancelFlightFollowing() */

void __thiscall
ATCPilotMenuItemCancelFlightFollowing::~ATCPilotMenuItemCancelFlightFollowing
          (ATCPilotMenuItemCancelFlightFollowing *this)

{
  ATCPilotMenuParameter *pAVar1;
  ATCPilotMenuParameter *pAVar2;
  ATCPilotMenuParameter *pAVar3;
  
  *(undefined ***)this = &PTR__ATCPilotMenuItem_02aceb48;
  if (((byte)this[0x28] & 1) != 0) {
    operator_delete(*(void **)(this + 0x38));
  }
  pAVar1 = *(ATCPilotMenuParameter **)(this + 8);
  if (pAVar1 != (ATCPilotMenuParameter *)0x0) {
    pAVar2 = *(ATCPilotMenuParameter **)(this + 0x10);
    pAVar3 = pAVar1;
    if (pAVar2 != pAVar1) {
      do {
        pAVar2 = pAVar2 + -0x70;
        std::destroy_at<ATCPilotMenuParameter>(pAVar2);
      } while (pAVar2 != pAVar1);
      pAVar3 = *(ATCPilotMenuParameter **)(this + 8);
    }
    *(ATCPilotMenuParameter **)(this + 0x10) = pAVar1;
    operator_delete(pAVar3);
  }
  operator_delete(this);
  return;
}


// 001a08a0  ATCTaskRequestFlightFollowing::~ATCTaskRequestFlightFollowing

/* ATCTaskRequestFlightFollowing::~ATCTaskRequestFlightFollowing() */

void __thiscall
ATCTaskRequestFlightFollowing::~ATCTaskRequestFlightFollowing(ATCTaskRequestFlightFollowing *this)

{
  ATCAircraftResponseTask::~ATCAircraftResponseTask((ATCAircraftResponseTask *)this);
  return;
}


// 001a08b0  ATCTaskRequestFlightFollowing::~ATCTaskRequestFlightFollowing

/* ATCTaskRequestFlightFollowing::~ATCTaskRequestFlightFollowing() */

void __thiscall
ATCTaskRequestFlightFollowing::~ATCTaskRequestFlightFollowing(ATCTaskRequestFlightFollowing *this)

{
  ATCAircraftResponseTask::~ATCAircraftResponseTask((ATCAircraftResponseTask *)this);
  operator_delete(this);
  return;
}


// 001a0d50  ATCTaskCancelFlightFollowing::~ATCTaskCancelFlightFollowing

/* ATCTaskCancelFlightFollowing::~ATCTaskCancelFlightFollowing() */

void __thiscall
ATCTaskCancelFlightFollowing::~ATCTaskCancelFlightFollowing(ATCTaskCancelFlightFollowing *this)

{
  ATCAircraftResponseTask::~ATCAircraftResponseTask((ATCAircraftResponseTask *)this);
  return;
}


// 001a0d60  ATCTaskCancelFlightFollowing::~ATCTaskCancelFlightFollowing

/* ATCTaskCancelFlightFollowing::~ATCTaskCancelFlightFollowing() */

void __thiscall
ATCTaskCancelFlightFollowing::~ATCTaskCancelFlightFollowing(ATCTaskCancelFlightFollowing *this)

{
  ATCAircraftResponseTask::~ATCAircraftResponseTask((ATCAircraftResponseTask *)this);
  operator_delete(this);
  return;
}


// 001a1650  ATCAircraftFlightPlan::ATCAircraftFlightPlan

/* ATCAircraftFlightPlan::ATCAircraftFlightPlan(ATCAircraftFlightPlan const&) */

void __thiscall
ATCAircraftFlightPlan::ATCAircraftFlightPlan
          (ATCAircraftFlightPlan *this,ATCAircraftFlightPlan *param_1)

{
  *(undefined8 *)this = *(undefined8 *)param_1;
  std::string::string((string *)(this + 8),(string *)(param_1 + 8));
  std::string::string((string *)(this + 0x20),(string *)(param_1 + 0x20));
  std::string::string((string *)(this + 0x38),(string *)(param_1 + 0x38));
  std::string::string((string *)(this + 0x50),(string *)(param_1 + 0x50));
  *(undefined8 *)(this + 0x68) = *(undefined8 *)(param_1 + 0x68);
  std::string::string((string *)(this + 0x70),(string *)(param_1 + 0x70));
  std::string::string((string *)(this + 0x88),(string *)(param_1 + 0x88));
  this[0xa4] = param_1[0xa4];
  *(undefined4 *)(this + 0xa0) = *(undefined4 *)(param_1 + 0xa0);
  return;
}


// 001a4a00  std::__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>::~__shared_ptr_emplace

/* std::__shared_ptr_emplace<ATCTaskRequestFlightFollowing,
   std::allocator<ATCTaskRequestFlightFollowing> >::~__shared_ptr_emplace() */

void __thiscall
std::
__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>::
~__shared_ptr_emplace
          (__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>
           *this)

{
  *(undefined ***)this = &PTR____shared_ptr_emplace_02acf788;
  std::__shared_weak_count::~__shared_weak_count((__shared_weak_count *)this);
  return;
}


// 001a4a20  std::__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>::~__shared_ptr_emplace

/* std::__shared_ptr_emplace<ATCTaskRequestFlightFollowing,
   std::allocator<ATCTaskRequestFlightFollowing> >::~__shared_ptr_emplace() */

void __thiscall
std::
__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>::
~__shared_ptr_emplace
          (__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>
           *this)

{
  *(undefined ***)this = &PTR____shared_ptr_emplace_02acf788;
  std::__shared_weak_count::~__shared_weak_count((__shared_weak_count *)this);
  operator_delete(this);
  return;
}


// 001a4a50  std::__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>::__on_zero_shared

/* std::__shared_ptr_emplace<ATCTaskRequestFlightFollowing,
   std::allocator<ATCTaskRequestFlightFollowing> >::__on_zero_shared() */

void __thiscall
std::
__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>::
__on_zero_shared(__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>
                 *this)

{
                    /* WARNING: Could not recover jumptable at 0x001a4a5d. Too many branches */
                    /* WARNING: Treating indirect jump as call */
  (*(code *)**(undefined8 **)(this + 0x18))(this + 0x18);
  return;
}


// 001a4a60  std::__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>::__on_zero_shared_weak

/* std::__shared_ptr_emplace<ATCTaskRequestFlightFollowing,
   std::allocator<ATCTaskRequestFlightFollowing> >::__on_zero_shared_weak() */

void __thiscall
std::
__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>::
__on_zero_shared_weak
          (__shared_ptr_emplace<ATCTaskRequestFlightFollowing,std::allocator<ATCTaskRequestFlightFollowing>>
           *this)

{
  operator_delete(this);
  return;
}


// 001a4a70  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16>, void
   (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 001a4a80  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16>, void
   (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 001a4a90  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16>, void
   (ATCAircraft*, bool)>::__clone() const */

void std::__function::
     __func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>
     ::__clone(void)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02acf7d8;
  return;
}


// 001a4ab0  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16>, void
   (ATCAircraft*, bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02acf7d8;
  return;
}


// 001a4ac0  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16>, void
   (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 001a4ad0  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16>, void
   (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 001a4ae0  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16>, void
   (ATCAircraft*, bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  long *plVar1;
  long lVar2;
  ATCAircraft *pAVar3;
  long *plVar4;
  
  if (*param_2 != false) {
    pAVar3 = *param_1;
    *(undefined8 *)(pAVar3 + 0x1f0) = 0;
    plVar4 = *(long **)(pAVar3 + 0x1f8);
    *(undefined8 *)(pAVar3 + 0x1f8) = 0;
    if (plVar4 != (long *)0x0) {
      LOCK();
      plVar1 = plVar4 + 1;
      lVar2 = *plVar1;
      *plVar1 = *plVar1 + -1;
      UNLOCK();
      if (lVar2 == 0) {
        (**(code **)(*plVar4 + 0x10))(plVar4);
        std::__shared_weak_count::__release_weak();
        return;
      }
    }
  }
  return;
}


// 001a4b40  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16>, void
   (ATCAircraft*, bool)>::target(std::type_info const&) const */

__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>
::target(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__16>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController18SetFlightFollowingEP11ATCAircraftR7ATCTxonE4$_16") {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 001a4b60  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_16>, void
   (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_16::typeinfo;
}


// 001a4b70  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17>, void
   (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 001a4b80  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17>, void
   (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 001a4b90  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17>, void
   (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
          *this)

{
  undefined4 uVar1;
  undefined8 *puVar2;
  
  puVar2 = operator_new(0x10);
  uVar1 = *(undefined4 *)(this + 8);
  *puVar2 = &PTR____func_02acf858;
  *(undefined4 *)(puVar2 + 1) = uVar1;
  return;
}


// 001a4bc0  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17>, void
   (ATCAircraft*, bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined4 uVar1;
  
  uVar1 = *(undefined4 *)(this + 8);
  *(undefined ***)param_1 = &PTR____func_02acf858;
  *(undefined4 *)(param_1 + 8) = uVar1;
  return;
}


// 001a4be0  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17>, void
   (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 001a4bf0  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17>, void
   (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 001a4c00  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17>, void
   (ATCAircraft*, bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  long *plVar1;
  long lVar2;
  ATCAircraft *pAVar3;
  long *plVar4;
  
  if (*param_2 != false) {
    pAVar3 = *param_1;
    (**(code **)(*(long *)pAVar3 + 0x148))(pAVar3,*(undefined2 *)(this + 8));
    *(long *)(pAVar3 + 0x1f0) = 0;
    plVar4 = *(long **)(pAVar3 + 0x1f8);
    *(long *)(pAVar3 + 0x1f8) = 0;
    if (plVar4 != (long *)0x0) {
      LOCK();
      plVar1 = plVar4 + 1;
      lVar2 = *plVar1;
      *plVar1 = *plVar1 + -1;
      UNLOCK();
      if (lVar2 == 0) {
        (**(code **)(*plVar4 + 0x10))(plVar4);
        std::__shared_weak_count::__release_weak();
        return;
      }
    }
  }
  return;
}


// 001a4c70  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17>, void
   (ATCAircraft*, bool)>::target(std::type_info const&) const */

__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>
::target(__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::__17>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController18SetFlightFollowingEP11ATCAircraftR7ATCTxonE4$_17") {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 001a4c90  std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17,
   std::allocator<ATCController::SetFlightFollowing(ATCAircraft*, ATCTxon&)::$_17>, void
   (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17,std::allocator<ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::SetFlightFollowing(ATCAircraft*,ATCTxon&)::$_17::typeinfo;
}


// 001a7280  std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>::~__shared_ptr_emplace

/* std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,
   std::allocator<ATCTaskCancelFlightFollowing> >::~__shared_ptr_emplace() */

void __thiscall
std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>
::~__shared_ptr_emplace
          (__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>
           *this)

{
  *(undefined ***)this = &PTR____shared_ptr_emplace_02ad05d8;
  std::__shared_weak_count::~__shared_weak_count((__shared_weak_count *)this);
  return;
}


// 001a72a0  std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>::~__shared_ptr_emplace

/* std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,
   std::allocator<ATCTaskCancelFlightFollowing> >::~__shared_ptr_emplace() */

void __thiscall
std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>
::~__shared_ptr_emplace
          (__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>
           *this)

{
  *(undefined ***)this = &PTR____shared_ptr_emplace_02ad05d8;
  std::__shared_weak_count::~__shared_weak_count((__shared_weak_count *)this);
  operator_delete(this);
  return;
}


// 001a72d0  std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>::__on_zero_shared

/* std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,
   std::allocator<ATCTaskCancelFlightFollowing> >::__on_zero_shared() */

void __thiscall
std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>
::__on_zero_shared(__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>
                   *this)

{
                    /* WARNING: Could not recover jumptable at 0x001a72dd. Too many branches */
                    /* WARNING: Treating indirect jump as call */
  (*(code *)**(undefined8 **)(this + 0x18))(this + 0x18);
  return;
}


// 001a72e0  std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>::__on_zero_shared_weak

/* std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,
   std::allocator<ATCTaskCancelFlightFollowing> >::__on_zero_shared_weak() */

void __thiscall
std::__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>
::__on_zero_shared_weak
          (__shared_ptr_emplace<ATCTaskCancelFlightFollowing,std::allocator<ATCTaskCancelFlightFollowing>>
           *this)

{
  operator_delete(this);
  return;
}


// 001a72f0  std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,
   std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>, void
   (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 001a7300  std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,
   std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>, void
   (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 001a7310  std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,
   std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>, void
   (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
          *this)

{
  undefined2 uVar1;
  undefined8 *puVar2;
  
  puVar2 = operator_new(0x10);
  uVar1 = *(undefined2 *)(this + 8);
  *puVar2 = &PTR____func_02ad0628;
  *(undefined2 *)(puVar2 + 1) = uVar1;
  return;
}


// 001a7340  std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,
   std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>, void
   (ATCAircraft*, bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined2 uVar1;
  
  uVar1 = *(undefined2 *)(this + 8);
  *(undefined ***)param_1 = &PTR____func_02ad0628;
  *(undefined2 *)(param_1 + 8) = uVar1;
  return;
}


// 001a7360  std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,
   std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>, void
   (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 001a7370  std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,
   std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>, void
   (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 001a7380  std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,
   std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>, void
   (ATCAircraft*, bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  ATCAircraft *pAVar1;
  
  if (*param_2 != false) {
    pAVar1 = *param_1;
    (**(code **)(*(long *)pAVar1 + 0x148))(pAVar1,*(undefined2 *)(this + 8));
                    /* WARNING: Could not recover jumptable at 0x001a73aa. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (**(code **)(*(long *)pAVar1 + 0x188))(pAVar1);
    return;
  }
  return;
}


// 001a73c0  std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,
   std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>, void
   (ATCAircraft*, bool)>::target(std::type_info const&) const */

__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>
::target(__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::__29>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController27HandleCancelFlightFollowingEP11ATCAircraftE4$_29") {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 001a73e0  std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,
   std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>, void
   (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29,std::allocator<ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::HandleCancelFlightFollowing(ATCAircraft*)::$_29::typeinfo;
}


// 001b8f90  ATCFlightRoute::IsEmpty

/* ATCFlightRoute::IsEmpty() const */

bool __thiscall ATCFlightRoute::IsEmpty(ATCFlightRoute *this)

{
  if (*(long *)this != 0) {
    return *(long *)(this + 8) == 0;
  }
  return true;
}


// 001beb10  ATCFlightRoute::GetStart

/* ATCFlightRoute::GetStart() */

undefined8 __thiscall ATCFlightRoute::GetStart(ATCFlightRoute *this)

{
  return *(undefined8 *)this;
}


// 001beb30  ATCFlightSegment::GetLength

/* ATCFlightSegment::GetLength() const */

void __thiscall ATCFlightSegment::GetLength(ATCFlightSegment *this)

{
  long lVar1;
  long lVar2;
  UTL_geoid *pUVar3;
  
  lVar1 = *(long *)(this + 0x88);
  lVar2 = *(long *)(this + 0x90);
  pUVar3 = (UTL_geoid *)REN_geoid::instance();
  ATCGeomDistBetweenLonLatPts(pUVar3,(GeoPoint2D *)(lVar2 + 0x40),(GeoPoint2D *)(lVar1 + 0x40));
  return;
}


// 001beb70  ATCFlightSegment::GetNextSeg

/* ATCFlightSegment::GetNextSeg() */

undefined8 __thiscall ATCFlightSegment::GetNextSeg(ATCFlightSegment *this)

{
  if (*(long *)(this + 0x88) != 0) {
    return *(undefined8 *)(*(long *)(this + 0x88) + 0x90);
  }
  return 0;
}


// 001bf8a0  ATCFlightSegment::GetSrcPt

/* ATCFlightSegment::GetSrcPt() const */

undefined8 __thiscall ATCFlightSegment::GetSrcPt(ATCFlightSegment *this)

{
  return *(undefined8 *)(this + 0x90);
}


// 001c0120  ATCFlightSegment::GetNextSeg

/* ATCFlightSegment::GetNextSeg() const */

undefined8 __thiscall ATCFlightSegment::GetNextSeg(ATCFlightSegment *this)

{
  if (*(long *)(this + 0x88) != 0) {
    return *(undefined8 *)(*(long *)(this + 0x88) + 0x90);
  }
  return 0;
}


// 001c0150  ATCFlightSegment::GetDstPt

/* ATCFlightSegment::GetDstPt() const */

undefined8 __thiscall ATCFlightSegment::GetDstPt(ATCFlightSegment *this)

{
  return *(undefined8 *)(this + 0x88);
}


// 001c05a0  ATCFlightRoute::GetEnd

/* ATCFlightRoute::GetEnd() */

undefined8 __thiscall ATCFlightRoute::GetEnd(ATCFlightRoute *this)

{
  return *(undefined8 *)(this + 8);
}


// 001ca3d0  ATCFlightRouteUtils::GetFirstSegOfType

/* ATCFlightRouteUtils::GetFirstSegOfType(ATCFlightRoute&, ATCFlightSegmentType, ATCFlightSegment*)
    */

int * ATCFlightRouteUtils::GetFirstSegOfType(long *param_1,int param_2,int *param_3)

{
  if ((*param_1 != 0) && (param_1[1] != 0)) {
    if (param_3 != (int *)0x0) goto LAB_001ca400;
    for (param_3 = *(int **)(*param_1 + 0x90); param_3 != (int *)0x0;
        param_3 = *(int **)(*(long *)(param_3 + 0x22) + 0x90)) {
LAB_001ca400:
      if (*param_3 == param_2) {
        return param_3;
      }
      if (*(long *)(param_3 + 0x22) == 0) {
        return (int *)0x0;
      }
    }
  }
  return (int *)0x0;
}


// 001ca420  ATCFlightSegment::GetTrueCourse

/* ATCFlightSegment::GetTrueCourse() const */

void __thiscall ATCFlightSegment::GetTrueCourse(ATCFlightSegment *this)

{
  invalid_argument *this_00;
  float fVar1;
  double dVar2;
  double dVar3;
  double dVar4;
  double dVar5;
  double dVar6;
  double dVar7;
  undefined8 extraout_XMM0_Qb;
  undefined1 auVar8 [16];
  undefined1 auVar9 [16];
  float fVar11;
  double dVar12;
  double dVar13;
  undefined8 uVar10;
  
  REN_geoid::instance();
  dVar2 = *(double *)(*(long *)(this + 0x90) + 0x40) * DAT_0253ae48;
  dVar12 = DAT_0253ae48 * *(double *)(*(long *)(this + 0x88) + 0x40);
  dVar13 = *(double *)(*(long *)(this + 0x90) + 0x48) * DAT_0253ae50;
  dVar7 = DAT_0253ae50 * *(double *)(*(long *)(this + 0x88) + 0x48);
  dVar3 = (double)_cos();
  dVar4 = (double)_sin((dVar2 - dVar12) * DAT_02520410);
  dVar5 = (double)_cos(dVar12);
  dVar6 = (double)_sin((dVar13 - dVar7) * DAT_02520410);
  dVar4 = (double)_asin(SQRT((double)((float)dVar6 * (float)dVar6) * dVar5 * dVar3 +
                             (double)((float)dVar4 * (float)dVar4)));
  dVar4 = dVar4 + dVar4;
  auVar9 = ZEXT816(0);
  if ((dVar4 != 0.0) || (NAN(dVar4))) {
    if (DAT_0253ae58 <= dVar3) {
      dVar5 = dVar4;
      dVar6 = (double)_sin(dVar7 - dVar13);
      dVar7 = (double)_sin(dVar12);
      dVar2 = (double)_sin(dVar2);
      dVar4 = (double)___sincos_stret(dVar4);
      dVar2 = (dVar7 - dVar5 * dVar2) / (dVar3 * dVar4);
      dVar7 = DAT_02520b70;
      if (dVar2 <= DAT_02520b70) {
        dVar7 = dVar2;
      }
      dVar7 = (double)_acos(-(ulong)(dVar2 < DAT_02520bb0) & (ulong)DAT_02520bb0 |
                            ~-(ulong)(dVar2 < DAT_02520bb0) & (ulong)dVar7);
      uVar10 = extraout_XMM0_Qb;
      if (0.0 <= dVar6) {
        dVar7 = DAT_0253ae60 - dVar7;
        uVar10 = 0;
      }
    }
    else {
      dVar7 = *(double *)(&DAT_0253aac0 + (ulong)(0.0 < dVar2) * 8);
      uVar10 = 0;
    }
    auVar8._0_8_ = dVar7 * DAT_0253ae68;
    auVar8._8_8_ = uVar10;
    auVar9._4_12_ = auVar8._4_12_;
    auVar9._0_4_ = (float)auVar8._0_8_;
    fVar11 = auVar9._0_4_;
    while (fVar1 = auVar9._0_4_, fVar11 < 0.0) {
      auVar9._0_4_ = fVar1 + DAT_02520bc4;
      fVar11 = auVar9._0_4_;
    }
    while (DAT_02520bc4 < fVar1) {
      auVar9._0_4_ = auVar9._0_4_ + DAT_02520bd8;
      fVar1 = auVar9._0_4_;
    }
  }
  fVar11 = (float)(((double)auVar9._0_4_ * DAT_02520238) / DAT_02520230);
  fVar11 = fVar11 - (float)(int)((double)fVar11 / DAT_02520250) * DAT_02520294;
  fVar11 = (float)(~-(uint)(fVar11 < 0.0) & (uint)fVar11 |
                  (uint)(DAT_02520294 + fVar11) & -(uint)(fVar11 < 0.0));
  if ((0.0 <= fVar11) && (fVar11 <= DAT_02520294)) {
    return;
  }
  this_00 = (invalid_argument *)___cxa_allocate_exception(0x10);
  std::invalid_argument::invalid_argument(this_00,"Course must be between 0 and 2*Pi");
                    /* WARNING: Subroutine does not return */
  ___cxa_throw(this_00,PTR_typeinfo_02ac0288,PTR__invalid_argument_02ac00e8);
}


// 001caf50  ATCFlightRouteUtils::GetLandingTypeSeg

/* ATCFlightRouteUtils::GetLandingTypeSeg(ATCFlightRoute&) */

int * ATCFlightRouteUtils::GetLandingTypeSeg(ATCFlightRoute *param_1)

{
  int *piVar1;
  
  if ((*(long *)param_1 != 0) && (*(long *)(param_1 + 8) != 0)) {
    for (piVar1 = *(int **)(*(long *)param_1 + 0x90); piVar1 != (int *)0x0;
        piVar1 = *(int **)(*(long *)(piVar1 + 0x22) + 0x90)) {
      if ((*piVar1 == 7) && (piVar1[2] - 2U < 4)) {
        return piVar1;
      }
      if (*(long *)(piVar1 + 0x22) == 0) {
        return (int *)0x0;
      }
    }
  }
  return (int *)0x0;
}


// 001cafb0  ATCFlightRoute::DistanceToRun

/* ATCFlightRoute::DistanceToRun(GeoPoint2D const&, ATCFlightSegment const*, ATCWaypoint const*) */

ulong __thiscall
ATCFlightRoute::DistanceToRun
          (ATCFlightRoute *this,GeoPoint2D *param_1,ATCFlightSegment *param_2,ATCWaypoint *param_3)

{
  double dVar1;
  long lVar2;
  long lVar3;
  ATCWaypoint *pAVar4;
  UTL_geoid *pUVar5;
  float fVar6;
  ulong uVar7;
  double dVar8;
  undefined8 local_48;
  double dStack_40;
  float local_34;
  
  if (*(long *)this == 0) {
    return 0;
  }
  lVar2 = *(long *)(param_2 + 0x88);
  lVar3 = *(long *)(param_2 + 0x90);
  pUVar5 = (UTL_geoid *)REN_geoid::instance();
  dVar8 = *(double *)(lVar3 + 0x40);
  dVar1 = *(double *)(lVar2 + 0x40);
  if ((dVar8 != dVar1) || (NAN(dVar8) || NAN(dVar1))) {
LAB_001cb009:
    if (dVar8 == DAT_0253ae78) {
      if ((dVar1 == DAT_0253ae78) && (!NAN(dVar1) && !NAN(DAT_0253ae78))) goto LAB_001cb065;
    }
    if (dVar8 == DAT_0253ae80) {
      if ((dVar1 == DAT_0253ae80) && (!NAN(dVar1) && !NAN(DAT_0253ae80))) goto LAB_001cb065;
    }
    fVar6 = (float)ATCGeomDistBetweenLonLatPts
                             (pUVar5,(GeoPoint2D *)(lVar3 + 0x40),(GeoPoint2D *)(lVar2 + 0x40));
    if (DAT_0253ae88 <= (double)fVar6) {
      lVar2 = *(long *)(param_2 + 0x88);
      lVar3 = *(long *)(param_2 + 0x90);
      dVar8 = DAT_0253ae88;
      pUVar5 = (UTL_geoid *)REN_geoid::instance();
      local_48 = ATCGeomProjectPointRoundWorld
                           (pUVar5,(GeoPoint2D *)(lVar3 + 0x40),(GeoPoint2D *)(lVar2 + 0x40),param_1
                           );
      pAVar4 = *(ATCWaypoint **)(param_2 + 0x90);
      dStack_40 = dVar8;
      goto joined_r0x001cb170;
    }
  }
  else if ((*(double *)(lVar3 + 0x48) != *(double *)(lVar2 + 0x48)) ||
          (NAN(*(double *)(lVar3 + 0x48)) || NAN(*(double *)(lVar2 + 0x48)))) goto LAB_001cb009;
LAB_001cb065:
  local_48 = *(undefined8 *)param_1;
  dStack_40 = *(double *)(param_1 + 8);
  pAVar4 = *(ATCWaypoint **)(param_2 + 0x90);
joined_r0x001cb170:
  if ((pAVar4 == param_3) || (pAVar4 = *(ATCWaypoint **)(param_2 + 0x88), pAVar4 == param_3)) {
    pUVar5 = (UTL_geoid *)REN_geoid::instance();
    uVar7 = ATCGeomDistBetweenLonLatPts
                      (pUVar5,(GeoPoint2D *)&local_48,(GeoPoint2D *)(param_3 + 0x40));
  }
  else {
    pUVar5 = (UTL_geoid *)REN_geoid::instance();
    uVar7 = ATCGeomDistBetweenLonLatPts
                      (pUVar5,(GeoPoint2D *)&local_48,(GeoPoint2D *)(pAVar4 + 0x40));
    for (lVar2 = *(long *)(param_2 + 0x88); lVar2 != 0; lVar2 = *(long *)(lVar2 + 0x88)) {
      local_34 = (float)uVar7;
      lVar2 = *(long *)(lVar2 + 0x90);
      if (lVar2 == 0) {
        return uVar7;
      }
      pAVar4 = *(ATCWaypoint **)(lVar2 + 0x90);
      if (pAVar4 == param_3) {
        return uVar7;
      }
      lVar3 = *(long *)(lVar2 + 0x88);
      pUVar5 = (UTL_geoid *)REN_geoid::instance();
      fVar6 = (float)ATCGeomDistBetweenLonLatPts
                               (pUVar5,(GeoPoint2D *)(pAVar4 + 0x40),(GeoPoint2D *)(lVar3 + 0x40));
      uVar7 = (ulong)(uint)(local_34 + fVar6);
    }
  }
  return uVar7;
}


// 001d0190  ATCUtilsGenRandomUniqueFlightNumber

/* ATCUtilsGenRandomUniqueFlightNumber(airline_t) */

ulong * ATCUtilsGenRandomUniqueFlightNumber(ulong *param_1,int param_2)

{
  ulong *puVar1;
  int iVar2;
  mersenne_twister_engine *pmVar3;
  __tree_node_base *p_Var4;
  ulong uVar5;
  __tree_node_base *p_Var6;
  __tree_node_base *p_Var7;
  void *pvVar8;
  long lVar9;
  long *plVar10;
  undefined8 local_b8;
  ulong *local_b0;
  long *local_a8;
  long *plStack_a0;
  undefined8 local_98;
  undefined8 local_90;
  void *local_80;
  ulong local_78;
  ulong uStack_70;
  undefined1 *local_68;
  int local_54;
  long *local_50;
  __tree_node_base *local_48;
  __tree_node_base *local_40;
  long lStack_38;
  
  if (param_2 == -1) {
    *(undefined2 *)param_1 = 0;
    return param_1;
  }
  local_48 = (__tree_node_base *)&local_40;
  local_40 = (__tree_node_base *)0x0;
  lStack_38 = 0;
  local_a8 = (long *)0x0;
  plStack_a0 = (long *)0x0;
  local_98 = 0;
  local_b0 = param_1;
  local_54 = param_2;
  ATCAircraft::GetAll((vector *)&local_a8);
  local_50 = plStack_a0;
  plVar10 = local_a8;
  if (local_a8 != plStack_a0) {
    do {
      lVar9 = *plVar10;
      iVar2 = *(int *)(lVar9 + 0x248);
      if (iVar2 != -1) {
        p_Var7 = (__tree_node_base *)&local_40;
        p_Var6 = local_40;
        p_Var4 = p_Var7;
        if (local_40 == (__tree_node_base *)0x0) {
LAB_001d04da:
          p_Var6 = operator_new(0x40);
          *(undefined4 *)(p_Var6 + 0x20) = *(undefined4 *)(lVar9 + 0x248);
          *(undefined8 *)(p_Var6 + 0x30) = 0;
          *(undefined8 *)(p_Var6 + 0x38) = 0;
          *(__tree_node_base **)(p_Var6 + 0x28) = p_Var6 + 0x30;
          *(undefined8 *)p_Var6 = 0;
          *(undefined8 *)(p_Var6 + 8) = 0;
          *(__tree_node_base **)(p_Var6 + 0x10) = p_Var7;
          *(__tree_node_base **)p_Var4 = p_Var6;
          p_Var7 = p_Var6;
          if (*(__tree_node_base **)local_48 != (__tree_node_base *)0x0) {
            p_Var7 = *(__tree_node_base **)p_Var4;
            local_48 = *(__tree_node_base **)local_48;
          }
          std::__tree_balance_after_insert<std::__tree_node_base<void*>*>(local_40,p_Var7);
          lStack_38 = lStack_38 + 1;
          lVar9 = *plVar10;
        }
        else {
LAB_001d04be:
          do {
            p_Var7 = p_Var6;
            if (*(int *)(p_Var7 + 0x20) <= iVar2) {
              if (*(int *)(p_Var7 + 0x20) < iVar2) {
                p_Var4 = p_Var7 + 8;
                p_Var6 = *(__tree_node_base **)(p_Var7 + 8);
                if (*(__tree_node_base **)(p_Var7 + 8) != (__tree_node_base *)0x0)
                goto LAB_001d04be;
              }
              p_Var6 = *(__tree_node_base **)p_Var4;
              if (p_Var6 != (__tree_node_base *)0x0) goto LAB_001d045c;
              goto LAB_001d04da;
            }
            p_Var6 = *(__tree_node_base **)p_Var7;
            p_Var4 = p_Var7;
          } while (*(__tree_node_base **)p_Var7 != (__tree_node_base *)0x0);
          p_Var6 = *(__tree_node_base **)p_Var7;
          if (p_Var6 == (__tree_node_base *)0x0) goto LAB_001d04da;
        }
LAB_001d045c:
        std::__tree<std::string,std::less<std::string>,std::allocator<std::string>>::
        __emplace_unique_key_args<std::string,std::string_const&>
                  ((__tree<std::string,std::less<std::string>,std::allocator<std::string>> *)
                   (p_Var6 + 0x28),(string *)(lVar9 + 0x250),(string *)(lVar9 + 0x250));
      }
      plVar10 = plVar10 + 1;
    } while (plVar10 != local_50);
  }
  local_78 = 0;
  uStack_70 = 0;
  local_68 = (undefined1 *)0x0;
  local_50 = (long *)((ulong)local_50 & 0xffffffff00000000);
  do {
    local_90 = 0x200000000;
    pmVar3 = (mersenne_twister_engine *)rand_gen();
    iVar2 = std::uniform_int_distribution<int>::operator()
                      ((uniform_int_distribution<int> *)&local_90,pmVar3,(param_type *)&local_90);
    if (0 < iVar2) {
      do {
        local_90 = 0x1900000000;
        pmVar3 = (mersenne_twister_engine *)rand_gen();
        std::uniform_int_distribution<int>::operator()
                  ((uniform_int_distribution<int> *)&local_90,pmVar3,(param_type *)&local_90);
        std::string::push_back((char)(string *)&local_78);
        iVar2 = iVar2 + -1;
      } while (iVar2 != 0);
    }
    local_b8 = 0x270f00000064;
    pmVar3 = (mersenne_twister_engine *)rand_gen();
    iVar2 = std::uniform_int_distribution<int>::operator()
                      ((uniform_int_distribution<int> *)&local_b8,pmVar3,(param_type *)&local_b8);
    int_to_str((uniform_int_distribution<int> *)&local_90,iVar2,1,0,0);
    iVar2 = local_54;
    pvVar8 = local_80;
    if ((local_90 & 1) == 0) {
      pvVar8 = (void *)((long)&local_90 + 1);
    }
    std::string::append((char *)&local_78,(ulong)pvVar8);
    if ((local_90 & 1) == 0) {
      p_Var4 = local_40;
      p_Var7 = (__tree_node_base *)&local_40;
      if (local_40 == (__tree_node_base *)0x0) goto LAB_001d0356;
LAB_001d037e:
      do {
        p_Var6 = p_Var4;
        if (*(int *)(p_Var6 + 0x20) <= iVar2) {
          if (*(int *)(p_Var6 + 0x20) < iVar2) {
            p_Var7 = p_Var6 + 8;
            p_Var4 = *(__tree_node_base **)(p_Var6 + 8);
            if (*(__tree_node_base **)(p_Var6 + 8) != (__tree_node_base *)0x0) goto LAB_001d037e;
          }
          p_Var4 = *(__tree_node_base **)p_Var7;
          goto joined_r0x001d0399;
        }
        p_Var4 = *(__tree_node_base **)p_Var6;
        p_Var7 = p_Var6;
      } while (*(__tree_node_base **)p_Var6 != (__tree_node_base *)0x0);
      p_Var4 = *(__tree_node_base **)p_Var6;
    }
    else {
      operator_delete(local_80);
      p_Var4 = local_40;
      p_Var7 = (__tree_node_base *)&local_40;
      if (local_40 != (__tree_node_base *)0x0) goto LAB_001d037e;
LAB_001d0356:
      p_Var6 = (__tree_node_base *)&local_40;
      p_Var4 = local_40;
      p_Var7 = p_Var6;
    }
joined_r0x001d0399:
    if (p_Var4 == (__tree_node_base *)0x0) {
      p_Var4 = operator_new(0x40);
      *(int *)(p_Var4 + 0x20) = local_54;
      *(undefined8 *)(p_Var4 + 0x30) = 0;
      *(undefined8 *)(p_Var4 + 0x38) = 0;
      *(__tree_node_base **)(p_Var4 + 0x28) = p_Var4 + 0x30;
      *(undefined8 *)p_Var4 = 0;
      *(undefined8 *)(p_Var4 + 8) = 0;
      *(__tree_node_base **)(p_Var4 + 0x10) = p_Var6;
      *(__tree_node_base **)p_Var7 = p_Var4;
      p_Var6 = p_Var4;
      if (*(__tree_node_base **)local_48 != (__tree_node_base *)0x0) {
        p_Var6 = *(__tree_node_base **)p_Var7;
        local_48 = *(__tree_node_base **)local_48;
      }
      std::__tree_balance_after_insert<std::__tree_node_base<void*>*>(local_40,p_Var6);
      lStack_38 = lStack_38 + 1;
    }
    uVar5 = std::__tree<std::string,std::less<std::string>,std::allocator<std::string>>::
            __count_unique<std::string>
                      ((__tree<std::string,std::less<std::string>,std::allocator<std::string>> *)
                       (p_Var4 + 0x28),(string *)&local_78);
    puVar1 = local_b0;
    if (uVar5 == 0) break;
    if ((local_78 & 1) == 0) {
      local_78 = local_78 & 0xffffffffffff0000;
    }
    else {
      *local_68 = 0;
      uStack_70 = 0;
    }
    iVar2 = (int)local_50 + 1;
    local_50 = (long *)CONCAT44(local_50._4_4_,iVar2);
  } while (iVar2 != 100);
  if ((local_78 & 1) == 0) {
    if ((byte)local_78._0_1_ >> 1 != 0) goto LAB_001d0574;
  }
  else if (uStack_70 != 0) goto LAB_001d0574;
  std::string::assign((char *)&local_78);
LAB_001d0574:
  puVar1[2] = (ulong)local_68;
  *puVar1 = local_78;
  puVar1[1] = uStack_70;
  if (local_a8 != (long *)0x0) {
    plStack_a0 = local_a8;
    operator_delete(local_a8);
  }
  std::
  __tree<std::__value_type<airline_t,std::set<std::string,std::less<std::string>,std::allocator<std::string>>>,std::__map_value_compare<airline_t,std::__value_type<airline_t,std::set<std::string,std::less<std::string>,std::allocator<std::string>>>,std::less<airline_t>,true>,std::allocator<std::__value_type<airline_t,std::set<std::string,std::less<std::string>,std::allocator<std::string>>>>>
  ::destroy((__tree<std::__value_type<airline_t,std::set<std::string,std::less<std::string>,std::allocator<std::string>>>,std::__map_value_compare<airline_t,std::__value_type<airline_t,std::set<std::string,std::less<std::string>,std::allocator<std::string>>>,std::less<airline_t>,true>,std::allocator<std::__value_type<airline_t,std::set<std::string,std::less<std::string>,std::allocator<std::string>>>>>
             *)&local_48,(__tree_node *)local_40);
  return puVar1;
}


// 001d3e70  ATCFlightRoute::operator=

/* ATCFlightRoute::TEMPNAMEPLACEHOLDERVALUE(ATCFlightRoute&&) */

ATCFlightRoute * __thiscall ATCFlightRoute::operator=(ATCFlightRoute *this,ATCFlightRoute *param_1)

{
  ATCFlightRoute *pAVar1;
  byte bVar2;
  ATCFlightSegment *pAVar3;
  ATCNetwork_halfedge *this_00;
  undefined8 uVar4;
  byte *pbVar5;
  long lVar6;
  byte *pbVar7;
  
  *(int *)(this + 0x1c) = *(int *)(this + 0x1c) + 1;
  this[0x18] = (ATCFlightRoute)0x1;
  if (*(byte **)this != (byte *)0x0) {
    pbVar7 = *(byte **)(this + 8);
    pbVar5 = *(byte **)this;
    while (pbVar7 != (byte *)0x0) {
      pAVar3 = *(ATCFlightSegment **)(pbVar5 + 0x90);
      if (pAVar3 == (ATCFlightSegment *)0x0) {
        pbVar7 = (byte *)0x0;
        bVar2 = *pbVar5;
      }
      else {
        pbVar7 = *(byte **)(pAVar3 + 0x88);
        ATCFlightSegment::~ATCFlightSegment(pAVar3);
        operator_delete(pAVar3);
        bVar2 = *pbVar5;
      }
      if ((bVar2 & 1) != 0) {
        operator_delete(*(void **)(pbVar5 + 0x10));
      }
      operator_delete(pbVar5);
      pbVar5 = pbVar7;
    }
  }
  *(undefined8 *)this = 0;
  *(undefined8 *)(this + 8) = 0;
  lVar6 = *(long *)param_1;
  uVar4 = *(undefined8 *)(param_1 + 8);
  *(long *)this = lVar6;
  *(undefined8 *)(this + 8) = uVar4;
  while (lVar6 != 0) {
    while( true ) {
      pAVar3 = *(ATCFlightSegment **)(lVar6 + 0x90);
      if (pAVar3 == (ATCFlightSegment *)0x0) goto LAB_001d3f7c;
      this_00 = *(ATCNetwork_halfedge **)(pAVar3 + 0xf8);
      if (this_00 != (ATCNetwork_halfedge *)0x0) break;
      *(undefined8 *)(pAVar3 + 0x98) = *(undefined8 *)(this + 0x10);
      lVar6 = *(long *)(pAVar3 + 0x88);
      if (lVar6 == 0) goto LAB_001d3f7c;
    }
    ATCNetwork_halfedge::rem_occupier(this_00,pAVar3);
    *(undefined8 *)(pAVar3 + 0x98) = *(undefined8 *)(this + 0x10);
    ATCNetwork_halfedge::add_occupier(this_00,pAVar3);
    lVar6 = *(long *)(pAVar3 + 0x88);
  }
LAB_001d3f7c:
  *(int *)(param_1 + 0x1c) = *(int *)(param_1 + 0x1c) + 1;
  param_1[0x18] = (ATCFlightRoute)0x1;
  *(undefined1 (*) [16])param_1 = (undefined1  [16])0x0;
  pAVar1 = this + 0x1c;
  *(int *)pAVar1 = *(int *)pAVar1 + -1;
  if (((*(int *)pAVar1 == 0) && (this[0x18] = (ATCFlightRoute)0x0, *(long *)this != 0)) &&
     (*(long *)(this + 8) != 0)) {
    UpdateAltEst(this);
    UpdateETAs(this);
  }
  pAVar1 = param_1 + 0x1c;
  *(int *)pAVar1 = *(int *)pAVar1 + -1;
  if (((*(int *)pAVar1 == 0) && (param_1[0x18] = (ATCFlightRoute)0x0, *(long *)param_1 != 0)) &&
     (*(long *)(param_1 + 8) != 0)) {
    UpdateAltEst(param_1);
    UpdateETAs(param_1);
  }
  return this;
}


// 001d4010  ATCFlightRoute::ATCFlightRoute

/* ATCFlightRoute::ATCFlightRoute(ATCFlightRoute&&) */

void __thiscall ATCFlightRoute::ATCFlightRoute(ATCFlightRoute *this,ATCFlightRoute *param_1)

{
  *(undefined4 *)(this + 0x1c) = 0;
  *(undefined8 *)this = 0;
  *(undefined8 *)(this + 8) = 0;
  *(undefined8 *)(this + 9) = 0;
  *(undefined8 *)(this + 0x11) = 0;
  *(undefined8 *)(this + 0x10) = *(undefined8 *)(param_1 + 0x10);
  operator=(this,param_1);
  *(undefined8 *)(param_1 + 0x10) = 0;
  return;
}


// 001d4050  ATCFlightRoute::StartEdit

/* ATCFlightRoute::StartEdit() */

void __thiscall ATCFlightRoute::StartEdit(ATCFlightRoute *this)

{
  *(int *)(this + 0x1c) = *(int *)(this + 0x1c) + 1;
  this[0x18] = (ATCFlightRoute)0x1;
  return;
}


// 001d4060  ATCFlightRoute::Clear

/* ATCFlightRoute::Clear() */

void __thiscall ATCFlightRoute::Clear(ATCFlightRoute *this)

{
  byte bVar1;
  ATCFlightSegment *this_00;
  byte *pbVar2;
  byte *pbVar3;
  
  if (*(byte **)this != (byte *)0x0) {
    pbVar3 = *(byte **)(this + 8);
    pbVar2 = *(byte **)this;
    while (pbVar3 != (byte *)0x0) {
      this_00 = *(ATCFlightSegment **)(pbVar2 + 0x90);
      if (this_00 == (ATCFlightSegment *)0x0) {
        pbVar3 = (byte *)0x0;
        bVar1 = *pbVar2;
      }
      else {
        pbVar3 = *(byte **)(this_00 + 0x88);
        ATCFlightSegment::~ATCFlightSegment(this_00);
        operator_delete(this_00);
        bVar1 = *pbVar2;
      }
      if ((bVar1 & 1) != 0) {
        operator_delete(*(void **)(pbVar2 + 0x10));
      }
      operator_delete(pbVar2);
      pbVar2 = pbVar3;
    }
  }
  *(undefined8 *)this = 0;
  *(undefined8 *)(this + 8) = 0;
  return;
}


// 001d40f0  ATCFlightSegment::GetUnderlying

/* ATCFlightSegment::GetUnderlying() const */

undefined8 __thiscall ATCFlightSegment::GetUnderlying(ATCFlightSegment *this)

{
  return *(undefined8 *)(this + 0xf8);
}


// 001d43f0  ATCFlightRoute::FinishEdit

/* ATCFlightRoute::FinishEdit(bool) */

void __thiscall ATCFlightRoute::FinishEdit(ATCFlightRoute *this,bool param_1)

{
  ATCFlightRoute *pAVar1;
  undefined1 *puVar2;
  byte local_30;
  undefined1 local_2f [15];
  undefined1 *local_20;
  
  pAVar1 = this + 0x1c;
  *(int *)pAVar1 = *(int *)pAVar1 + -1;
  if (((*(int *)pAVar1 == 0) && (this[0x18] = (ATCFlightRoute)0x0, *(long *)this != 0)) &&
     (*(long *)(this + 8) != 0)) {
    UpdateAltEst(this);
    UpdateETAs(this);
    if (param_1) {
      (**(code **)(**(long **)(this + 0x10) + 0x3f8))(&local_30);
      puVar2 = local_20;
      if ((local_30 & 1) == 0) {
        puVar2 = local_2f;
      }
      _source_sim_log_write(0,"ATC","Route change for %s\n",puVar2);
      if ((local_30 & 1) != 0) {
        operator_delete(local_20);
      }
      PrintRoutingWithFunc(this,atc_log_func,(void *)0x0,true);
    }
  }
  return;
}


// 001d44d0  ATCFlightRoute::ATCFlightRoute

/* ATCFlightRoute::ATCFlightRoute(ATCAircraft const*) */

void __thiscall ATCFlightRoute::ATCFlightRoute(ATCFlightRoute *this,ATCAircraft *param_1)

{
  *(undefined8 *)this = 0;
  *(undefined8 *)(this + 8) = 0;
  *(ATCAircraft **)(this + 0x10) = param_1;
  this[0x18] = (ATCFlightRoute)0x0;
  *(undefined4 *)(this + 0x1c) = 0;
  return;
}


// 001d44f0  ATCFlightRoute::~ATCFlightRoute

/* ATCFlightRoute::~ATCFlightRoute() */

void __thiscall ATCFlightRoute::~ATCFlightRoute(ATCFlightRoute *this)

{
  byte bVar1;
  ATCFlightSegment *this_00;
  byte *pbVar2;
  byte *pbVar3;
  
  pbVar2 = *(byte **)this;
  while (pbVar2 != (byte *)0x0) {
    this_00 = *(ATCFlightSegment **)(pbVar2 + 0x90);
    if (this_00 == (ATCFlightSegment *)0x0) {
      pbVar3 = (byte *)0x0;
      bVar1 = *pbVar2;
    }
    else {
      pbVar3 = *(byte **)(this_00 + 0x88);
      ATCFlightSegment::~ATCFlightSegment(this_00);
      operator_delete(this_00);
      bVar1 = *pbVar2;
    }
    if ((bVar1 & 1) != 0) {
      operator_delete(*(void **)(pbVar2 + 0x10));
    }
    operator_delete(pbVar2);
    pbVar2 = pbVar3;
  }
  return;
}


// 001d4570  ATCFlightRoute::GetStartSeg

/* ATCFlightRoute::GetStartSeg() const */

undefined8 __thiscall ATCFlightRoute::GetStartSeg(ATCFlightRoute *this)

{
  if (*(long *)this != 0) {
    return *(undefined8 *)(*(long *)this + 0x90);
  }
  return 0;
}


// 001d4590  ATCFlightRoute::GetEndSeg

/* ATCFlightRoute::GetEndSeg() const */

undefined8 __thiscall ATCFlightRoute::GetEndSeg(ATCFlightRoute *this)

{
  if (*(long *)(this + 8) != 0) {
    return *(undefined8 *)(*(long *)(this + 8) + 0x88);
  }
  return 0;
}


// 001d45c0  ATCFlightRoute::UpdateAltEst

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* ATCFlightRoute::UpdateAltEst() */

void __thiscall ATCFlightRoute::UpdateAltEst(ATCFlightRoute *this)

{
  long lVar1;
  long lVar2;
  bool bVar3;
  long lVar4;
  UTL_geoid *pUVar5;
  ulong uVar6;
  uint uVar7;
  float fVar8;
  float fVar9;
  float fVar10;
  float fVar11;
  float fVar12;
  float fVar13;
  float fVar14;
  
  lVar1 = *(long *)this;
  if ((*(float *)(lVar1 + 0x3c) == DAT_025246d0) &&
     (!NAN(*(float *)(lVar1 + 0x3c)) && !NAN(DAT_025246d0))) {
    fVar8 = (float)(**(code **)(**(long **)(this + 0x10) + 0x2d0))(*(long **)(this + 0x10),1);
    *(float *)(lVar1 + 0x3c) = ((fVar8 * DAT_02525330 * DAT_02525330) / DAT_02536f14) / DAT_02536f10
    ;
  }
  if (*(long *)(lVar1 + 0x90) != 0) {
    fVar8 = DAT_02525330;
    fVar12 = DAT_02536f10;
    fVar13 = DAT_02536f14;
    for (lVar1 = *(long *)(*(long *)(lVar1 + 0x90) + 0x88); lVar1 != 0;
        lVar1 = *(long *)(*(long *)(lVar1 + 0x90) + 0x88)) {
      if ((*(char *)(lVar1 + 0x54) == '\0') && (*(char *)(lVar1 + 0x5c) == '\0')) {
LAB_001d46a8:
        lVar4 = *(long *)(lVar1 + 0x88);
        fVar11 = *(float *)(*(long *)(lVar4 + 0x90) + 0x3c);
        if (*(char *)(lVar4 + 0xc0) == '\0') {
          fVar9 = (float)(**(code **)(**(long **)(this + 0x10) + 0x2c8))();
          lVar4 = *(long *)(lVar1 + 0x88);
          fVar8 = DAT_02525330;
          fVar13 = DAT_02536f14;
          fVar12 = DAT_02536f10;
        }
        else {
          fVar9 = *(float *)(lVar4 + 0xbc);
        }
        fVar9 = ((fVar9 * fVar8 * fVar8) / fVar13) / fVar12;
        if (*(char *)(lVar4 + 200) == '\0') {
          fVar10 = (float)(**(code **)(**(long **)(this + 0x10) + 0x2c8))();
          lVar4 = *(long *)(lVar1 + 0x88);
          fVar8 = DAT_02525330;
          fVar13 = DAT_02536f14;
          fVar12 = DAT_02536f10;
        }
        else {
          fVar10 = *(float *)(lVar4 + 0xc4);
        }
        fVar12 = ((fVar10 * fVar8 * fVar8) / fVar13) / fVar12;
        fVar13 = (fVar9 + fVar12) * DAT_025246bc;
        uVar7 = -(uint)(fVar12 == fVar9);
        lVar2 = *(long *)(lVar4 + 0x88);
        lVar4 = *(long *)(lVar4 + 0x90);
        pUVar5 = (UTL_geoid *)REN_geoid::instance();
        fVar8 = (float)ATCGeomDistBetweenLonLatPts
                                 (pUVar5,(GeoPoint2D *)(lVar4 + 0x40),(GeoPoint2D *)(lVar2 + 0x40));
        if ((fVar11 == DAT_025246d0) && (!NAN(fVar11) && !NAN(DAT_025246d0))) {
          fVar12 = (float)(**(code **)(**(long **)(this + 0x10) + 0x2d0))(*(long **)(this + 0x10),1)
          ;
          fVar11 = ((fVar12 * DAT_02525330 * DAT_02525330) / DAT_02536f14) / DAT_02536f10;
        }
        fVar9 = (float)((uint)fVar9 & uVar7 | ~uVar7 & (uint)fVar13);
        fVar12 = (float)(**(code **)(**(long **)(this + 0x10) + 0x300))(*(long **)(this + 0x10),2,0)
        ;
        fVar13 = fVar9 - fVar11;
        fVar13 = (float)(~-(uint)(0.0 <= fVar13) & ((uint)fVar13 ^ _DAT_02520b30) |
                        (uint)fVar13 & -(uint)(0.0 <= fVar13));
        fVar12 = fVar13 / fVar12;
        if ((fVar12 != 0.0) || (NAN(fVar12))) {
          fVar10 = 0.0;
          if (fVar13 <= 0.0) {
            fVar10 = fVar13;
          }
          fVar14 = 0.0;
          if (0.0 <= fVar13) {
            fVar14 = fVar13;
          }
          fVar8 = fVar8 * (fVar13 / fVar12) + 0.0;
          if (fVar8 <= fVar14) {
            fVar14 = fVar8;
          }
          fVar8 = (float)(-(uint)(fVar8 < fVar10) & (uint)fVar10 |
                         ~-(uint)(fVar8 < fVar10) & (uint)fVar14);
        }
        else {
          fVar8 = (fVar13 + 0.0) * DAT_025246bc;
        }
        uVar7 = -(uint)(fVar11 < fVar9);
        fVar11 = (float)(~uVar7 & ((uint)fVar8 ^ _DAT_02520b30) | uVar7 & (uint)fVar8) + fVar11;
        fVar8 = DAT_02525330;
        fVar13 = DAT_02536f14;
        fVar12 = DAT_02536f10;
        if (*(char *)(lVar1 + 0x54) != '\0') {
          fVar11 = ((fVar11 * DAT_02536f10 * DAT_02536f14) / DAT_02525330) / DAT_02525330;
          fVar9 = *(float *)(lVar1 + 0x50);
          if (*(char *)(lVar1 + 0x5c) == '\0') {
            if (fVar9 <= fVar11) {
              fVar11 = fVar9;
            }
          }
          else {
            fVar10 = *(float *)(lVar1 + 0x58);
            if (fVar11 <= *(float *)(lVar1 + 0x58)) {
              fVar10 = fVar11;
            }
            fVar11 = (float)(-(uint)(fVar11 < fVar9) & (uint)fVar9 |
                            ~-(uint)(fVar11 < fVar9) & (uint)fVar10);
          }
          goto LAB_001d4950;
        }
        if (*(char *)(lVar1 + 0x5c) != '\0') {
          fVar11 = ((fVar11 * DAT_02536f10 * DAT_02536f14) / DAT_02525330) / DAT_02525330;
          if (*(float *)(lVar1 + 0x58) <= fVar11) {
            fVar11 = *(float *)(lVar1 + 0x58);
          }
          goto LAB_001d4950;
        }
      }
      else {
        fVar11 = (float)*(ulong *)(lVar1 + 0x50);
        uVar6 = *(ulong *)(lVar1 + 0x50) & 0xff00000000;
        bVar3 = ((*(ulong *)(lVar1 + 0x58) & 0xff00000000) != 0) != (uVar6 != 0);
        if ((bVar3) || (uVar6 == 0)) {
          if (bVar3) goto LAB_001d46a8;
        }
        else {
          fVar9 = (float)*(ulong *)(lVar1 + 0x58);
          if ((fVar11 != fVar9) || (NAN(fVar11) || NAN(fVar9))) goto LAB_001d46a8;
        }
LAB_001d4950:
        fVar11 = ((fVar11 * fVar8 * fVar8) / fVar13) / fVar12;
      }
      *(float *)(lVar1 + 0x3c) = fVar11;
      if (*(long *)(lVar1 + 0x90) == 0) {
        return;
      }
    }
  }
  return;
}


// 001d49a0  ATCFlightRoute::UpdateETAs

/* ATCFlightRoute::UpdateETAs() */

void __thiscall ATCFlightRoute::UpdateETAs(ATCFlightRoute *this)

{
  double dVar1;
  double dVar2;
  ATCWaypoint *pAVar3;
  int *piVar4;
  double dVar5;
  double dVar6;
  double dVar7;
  double dVar8;
  char cVar9;
  int iVar10;
  long lVar11;
  UTL_geoid *pUVar12;
  long lVar13;
  int iVar14;
  float fVar15;
  float fVar16;
  undefined8 uVar17;
  double dVar18;
  undefined4 uVar20;
  double dVar19;
  undefined8 local_c8;
  double local_c0;
  double local_b8;
  double local_b0;
  double local_a8;
  double local_a0;
  double local_98;
  undefined8 uStack_90;
  double local_88;
  double dStack_80;
  double local_78;
  double dStack_70;
  float local_60;
  float local_5c;
  double local_58;
  double dStack_50;
  double local_48;
  undefined8 uStack_40;
  long local_38;
  
  local_38 = *(long *)PTR____stack_chk_guard_02ac0540;
  lVar11 = *(long *)this;
  if (lVar11 != 0) {
    if ((*(float *)(lVar11 + 0x38) == DAT_025246d0) &&
       (!NAN(*(float *)(lVar11 + 0x38)) && !NAN(DAT_025246d0))) {
      *(float *)(lVar11 + 0x38) = (float)DAT_0315d538;
    }
    if (*(long *)(lVar11 + 0x90) != 0) {
      pAVar3 = *(ATCWaypoint **)(*(long *)(lVar11 + 0x90) + 0x88);
      while (pAVar3 != (ATCWaypoint *)0x0) {
        piVar4 = *(int **)(pAVar3 + 0x88);
        if ((char)piVar4[0x3a] == '\0') {
          local_5c = (float)(**(code **)(**(long **)(this + 0x10) + 0x200))();
          if ((char)piVar4[0x3c] != '\0') goto LAB_001d4a52;
LAB_001d4b20:
          iVar14 = (**(code **)(**(long **)(this + 0x10) + 0x210))();
          iVar10 = *piVar4;
          if (1 < iVar10 - 5U) goto LAB_001d4a6b;
LAB_001d4b40:
          if (piVar4[0x20] < 1) goto LAB_001d4c20;
          local_78 = (double)CONCAT44(local_78._4_4_,iVar14);
          fVar15 = (float)(**(code **)(**(long **)(this + 0x10) + 0x220))();
          cVar9 = -0x7f;
          if (fVar15 == local_78._0_4_) {
            cVar9 = '\0';
          }
          if (local_78._0_4_ < fVar15) {
            cVar9 = '\x01';
          }
          if (fVar15 < local_78._0_4_) {
            cVar9 = -1;
          }
          if (-1 < cVar9) {
            fVar15 = local_78._0_4_;
          }
          if (cVar9 == -0x7f) {
            fVar15 = local_78._0_4_;
          }
LAB_001d4bb0:
          lVar11 = *(long *)this;
          lVar13 = *(long *)(lVar11 + 0x90);
          local_5c = fVar15;
joined_r0x001d4cf5:
          if (lVar13 == 0) goto LAB_001d4cfb;
LAB_001d4bc3:
          if (pAVar3 == *(ATCWaypoint **)(lVar13 + 0x88)) goto LAB_001d4d0b;
LAB_001d4bd8:
          lVar11 = *(long *)(piVar4 + 0x22);
          lVar13 = *(long *)(piVar4 + 0x24);
          pUVar12 = (UTL_geoid *)REN_geoid::instance();
          fVar16 = (float)ATCGeomDistBetweenLonLatPts
                                    (pUVar12,(GeoPoint2D *)(lVar13 + 0x40),
                                     (GeoPoint2D *)(lVar11 + 0x40));
          fVar15 = *(float *)(*(long *)(*(long *)(pAVar3 + 0x88) + 0x90) + 0x38);
LAB_001d5282:
          local_88 = (double)CONCAT44(local_88._4_4_,fVar15);
          if (*piVar4 != 1) goto LAB_001d4d40;
LAB_001d5297:
          *(float *)(pAVar3 + 0x38) = *(float *)(*(long *)(piVar4 + 0x24) + 0x38) + DAT_025201e4;
          lVar11 = *(long *)(pAVar3 + 0x90);
        }
        else {
          local_5c = (float)piVar4[0x39];
          if ((char)piVar4[0x3c] == '\0') goto LAB_001d4b20;
LAB_001d4a52:
          iVar14 = piVar4[0x3b];
          iVar10 = *piVar4;
          if (iVar10 - 5U < 2) goto LAB_001d4b40;
LAB_001d4a6b:
          fVar15 = DAT_0253ad7c;
          if (iVar10 == 2) goto LAB_001d4bb0;
          if (iVar10 != 7) {
LAB_001d4c20:
            local_78 = (double)CONCAT44(local_78._4_4_,iVar14);
            fVar15 = (float)(**(code **)(**(long **)(this + 0x10) + 0x208))();
            local_98 = (double)CONCAT44(local_98._4_4_,fVar15);
            cVar9 = -0x7f;
            if (fVar15 == local_5c) {
              cVar9 = '\0';
            }
            if (local_5c < fVar15) {
              cVar9 = '\x01';
            }
            (**(code **)(**(long **)(this + 0x10) + 0x2f0))();
            if (local_98._0_4_ < local_5c) {
              cVar9 = -1;
            }
            if ((cVar9 == -0x7f) || (-1 < cVar9)) {
              cVar9 = -0x7f;
              if (local_78._0_4_ == local_98._0_4_) {
                cVar9 = '\0';
              }
              if (local_98._0_4_ < local_78._0_4_) {
                cVar9 = '\x01';
              }
              if (local_78._0_4_ < local_98._0_4_) {
                cVar9 = -1;
              }
              local_5c = local_78._0_4_;
              if (-1 < cVar9) {
                local_5c = local_98._0_4_;
              }
              if (cVar9 == -0x7f) {
                local_5c = local_98._0_4_;
              }
            }
            (**(code **)(**(long **)(this + 0x10) + 0x3f0))();
            lVar11 = *(long *)this;
            lVar13 = *(long *)(lVar11 + 0x90);
            goto joined_r0x001d4cf5;
          }
          local_5c = (float)(**(code **)(**(long **)(this + 0x10) + 0x208))();
          local_5c = local_5c * DAT_02536f4c;
          cVar9 = -0x7f;
          if (local_5c == DAT_02536f50) {
            cVar9 = '\0';
          }
          if (local_5c < DAT_02536f50) {
            cVar9 = '\x01';
          }
          if (DAT_02536f50 < local_5c) {
            cVar9 = -1;
          }
          fVar15 = DAT_02536f50;
          if (-1 < cVar9) {
            fVar15 = local_5c;
          }
          if (cVar9 != -0x7f) goto LAB_001d4bb0;
          lVar11 = *(long *)this;
          lVar13 = *(long *)(lVar11 + 0x90);
          if (lVar13 != 0) goto LAB_001d4bc3;
LAB_001d4cfb:
          if (pAVar3 != (ATCWaypoint *)0x0) goto LAB_001d4bd8;
LAB_001d4d0b:
          if (*piVar4 != 1) {
            uVar17 = (**(code **)(**(long **)(this + 0x10) + 0x250))();
            fVar15 = (float)uVar17;
            uVar20 = (undefined4)((ulong)uVar17 >> 0x20);
            cVar9 = -0x7f;
            if (fVar15 == DAT_0253ad90) {
              cVar9 = '\0';
            }
            if (fVar15 < DAT_0253ad90) {
              cVar9 = '\x01';
            }
            if (DAT_0253ad90 < fVar15) {
              cVar9 = -1;
            }
            if (-1 < cVar9) {
              uVar20 = 0;
              fVar15 = DAT_0253ad90;
            }
            if (cVar9 == -0x7f) {
              uVar20 = 0;
              fVar15 = DAT_0253ad90;
            }
            local_5c = fVar15;
            local_58 = (double)(**(code **)(**(long **)(this + 0x10) + 0x268))();
            dStack_50 = (double)CONCAT44(uVar20,fVar15);
            fVar15 = (float)DistanceToRun(this,(GeoPoint2D *)&local_58,
                                          *(ATCFlightSegment **)(*(ATCWaypoint **)this + 0x90),
                                          *(ATCWaypoint **)this);
            local_60 = (fVar15 / local_5c) * DAT_0252534c;
            local_88 = *(double *)(*(long *)this + 0x40);
            local_78 = *(double *)(*(long *)this + 0x48);
            lVar11 = REN_geoid::instance();
            geoid::ECEF_with_latlonele
                      ((geoid *)(lVar11 + 0xb0),&local_58,&dStack_50,&local_48,local_88,local_78,0.0
                      );
            dVar8 = local_48;
            dVar7 = dStack_50;
            dVar6 = local_58;
            local_98 = *(double *)(lVar11 + 0x280);
            uStack_90 = *(undefined8 *)(lVar11 + 0x288);
            dVar5 = *(double *)(lVar11 + 0x2a0);
            local_78 = *(double *)(lVar11 + 0x2c0);
            dStack_70 = *(double *)(lVar11 + 0x2c8);
            local_88 = *(double *)(lVar11 + 0x2e0);
            dStack_80 = *(double *)(lVar11 + 0x2e8);
            dVar19 = *(double *)(lVar11 + 0x2b0);
            dVar18 = *(double *)(lVar11 + 0x290);
            dVar1 = *(double *)(lVar11 + 0x2d0);
            dVar2 = *(double *)(lVar11 + 0x2f0);
            local_a8 = *(double *)(pAVar3 + 0x40);
            local_a0 = *(double *)(pAVar3 + 0x48);
            lVar11 = REN_geoid::instance();
            geoid::ECEF_with_latlonele
                      ((geoid *)(lVar11 + 0xb0),&local_58,&dStack_50,&local_48,local_a8,local_a0,0.0
                      );
            local_88 = (double)(float)(local_48 * *(double *)(lVar11 + 0x2c0) +
                                       dStack_50 * *(double *)(lVar11 + 0x2a0) +
                                       *(double *)(lVar11 + 0x280) * local_58 +
                                      *(double *)(lVar11 + 0x2e0)) -
                       (double)(float)(local_88 +
                                      local_78 * dVar8 + local_98 * dVar6 + dVar5 * dVar7);
            dStack_70 = (double)(float)(dVar8 * dVar1 + dVar6 * dVar18 + dVar19 * dVar7 + dVar2) -
                        (double)(float)(*(double *)(lVar11 + 0x2f0) +
                                       *(double *)(lVar11 + 0x2d0) * local_48 +
                                       *(double *)(lVar11 + 0x2b0) * dStack_50 +
                                       *(double *)(lVar11 + 0x290) * local_58);
            dStack_80 = dStack_70;
            if ((local_88 != 0.0) || (NAN(local_88))) {
              local_78 = dStack_70;
              if ((dStack_70 != 0.0) || (NAN(dStack_70))) {
                dVar19 = dStack_70 * dStack_70 + local_88 * local_88;
                dVar18 = SQRT(dVar19);
                if ((dVar18 != 0.0) || (NAN(dVar18))) {
                  dVar19 = DAT_02520b70 / dVar18;
                  local_88 = local_88 * dVar19;
                  local_78 = dStack_70 * dVar19;
                }
              }
              else {
                dVar19 = (double)(~-(ulong)(0.0 < local_88) &
                                 -(ulong)(local_88 < 0.0) & DAT_02520bb0);
                local_88 = (double)(-(ulong)(0.0 < local_88) & (ulong)DAT_02520b70 | (ulong)dVar19);
                dStack_80 = 0.0;
              }
            }
            else {
              dVar19 = (double)(~-(ulong)(0.0 < dStack_70) &
                               -(ulong)(dStack_70 < 0.0) & DAT_02520bb0);
              local_78 = (double)(-(ulong)(0.0 < dStack_70) & (ulong)DAT_02520b70 | (ulong)dVar19);
              dStack_70 = 0.0;
            }
            pUVar12 = (UTL_geoid *)REN_geoid::instance();
            lVar11 = *(long *)(*(long *)(*(long *)this + 0x90) + 0x88);
            lVar13 = *(long *)(*(long *)(*(long *)this + 0x90) + 0x90);
            local_58 = *(double *)(lVar13 + 0x40);
            dStack_50 = *(double *)(lVar13 + 0x48);
            local_48 = *(double *)(lVar11 + 0x40);
            uStack_40 = *(undefined8 *)(lVar11 + 0x48);
            local_c8 = (**(code **)(**(long **)(this + 0x10) + 0x268))();
            local_c0 = dVar19;
            fVar15 = (float)ATCGeomRatioAlong(pUVar12,(GeoSegment *)&local_58,
                                              (GeoPoint2D *)&local_c8);
            dVar19 = 0.0;
            if ((fVar15 < 0.0) || (DAT_025201e8 < fVar15)) {
LAB_001d5229:
              dVar18 = (double)local_60 + DAT_0315d538;
            }
            else {
              (**(code **)(**(long **)(this + 0x10) + 0x2b0))(&local_b8);
              dVar19 = local_78 * local_b0 + local_88 * local_b8;
              if (dVar19 <= DAT_0253af28) goto LAB_001d5229;
              dVar19 = (double)local_60;
              dVar18 = DAT_0315d538 - dVar19;
            }
            *(float *)(*(long *)this + 0x38) = (float)dVar18;
            local_58 = (double)(**(code **)(**(long **)(this + 0x10) + 0x268))();
            dStack_50 = dVar19;
            fVar16 = (float)DistanceToRun(this,(GeoPoint2D *)&local_58,
                                          *(ATCFlightSegment **)(*(long *)this + 0x90),pAVar3);
            fVar15 = (float)DAT_0315d538;
            goto LAB_001d5282;
          }
          *(float *)(lVar11 + 0x38) = (float)DAT_0315d538;
          fVar16 = 0.0;
          if (*piVar4 == 1) goto LAB_001d5297;
LAB_001d4d40:
          *(float *)(pAVar3 + 0x38) =
               ((((fVar16 / local_5c) / DAT_02536f20) / DAT_02520bc0) / DAT_02520bc0) * DAT_02520bc0
               * DAT_02520bc0 + local_88._0_4_;
          lVar11 = *(long *)(pAVar3 + 0x90);
        }
        if (lVar11 == 0) break;
        pAVar3 = *(ATCWaypoint **)(lVar11 + 0x88);
      }
    }
  }
  if (*(long *)PTR____stack_chk_guard_02ac0540 != local_38) {
                    /* WARNING: Subroutine does not return */
    ___stack_chk_fail();
  }
  return;
}


// 001d5300  ATCFlightRoute::PrintRoutingLog

/* ATCFlightRoute::PrintRoutingLog(bool) const */

void __thiscall ATCFlightRoute::PrintRoutingLog(ATCFlightRoute *this,bool param_1)

{
  PrintRoutingWithFunc(this,atc_log_func,(void *)0x0,param_1);
  return;
}


// 001d5320  ATCFlightRoute::CountWaypoints

/* ATCFlightRoute::CountWaypoints() const */

long __thiscall ATCFlightRoute::CountWaypoints(ATCFlightRoute *this)

{
  long lVar1;
  long lVar2;
  
  lVar2 = *(long *)this;
  lVar1 = 0;
  do {
    if (lVar2 == *(long *)(this + 8)) {
      return lVar1;
    }
    while (*(long *)(lVar2 + 0x90) == 0) {
      lVar2 = 0;
      lVar1 = lVar1 + 1;
      if (*(long *)(this + 8) == 0) {
        return lVar1;
      }
    }
    lVar2 = *(long *)(*(long *)(lVar2 + 0x90) + 0x88);
    lVar1 = lVar1 + 1;
  } while( true );
}


// 001d53d0  ATCFlightSegment::GetSrcPt

/* ATCFlightSegment::GetSrcPt() */

undefined8 __thiscall ATCFlightSegment::GetSrcPt(ATCFlightSegment *this)

{
  return *(undefined8 *)(this + 0x90);
}


// 001d5400  ATCFlightRoute::CreateChain

/* ATCFlightRoute::CreateChain(std::vector<GeoPoint2D, std::allocator<GeoPoint2D> > const&,
   ATCWaypoint**, ATCWaypoint**) */

void __thiscall
ATCFlightRoute::CreateChain
          (ATCFlightRoute *this,vector *param_1,ATCWaypoint **param_2,ATCWaypoint **param_3)

{
  undefined8 uVar1;
  undefined8 uVar2;
  ATCWaypoint *pAVar3;
  undefined8 *puVar4;
  ulong uVar5;
  ulong uVar6;
  long lVar7;
  undefined8 *local_38;
  
  *param_2 = (ATCWaypoint *)0x0;
  *param_3 = (ATCWaypoint *)0x0;
  local_38 = *(undefined8 **)param_1;
  if ((long)*(undefined8 **)(param_1 + 8) - (long)local_38 == 0x10) {
    pAVar3 = operator_new(0xb0);
    uVar1 = *local_38;
    uVar2 = local_38[1];
    *(undefined8 *)(pAVar3 + 0x28) = 0;
    *(undefined8 *)(pAVar3 + 0x30) = 0;
    *(undefined8 *)(pAVar3 + 0x10) = 0;
    *(undefined8 *)(pAVar3 + 0x18) = 0;
    *(undefined8 *)pAVar3 = 0;
    *(undefined8 *)(pAVar3 + 8) = 0;
    *(undefined8 *)(pAVar3 + 0x1e) = 0;
    *(undefined8 *)(pAVar3 + 0x38) = 0xbf800000bf800000;
    pAVar3[0x54] = (ATCWaypoint)0x0;
    pAVar3[0x58] = (ATCWaypoint)0x0;
    pAVar3[0x5c] = (ATCWaypoint)0x0;
    pAVar3[0x60] = (ATCWaypoint)0x0;
    pAVar3[100] = (ATCWaypoint)0x0;
    pAVar3[0x68] = (ATCWaypoint)0x0;
    pAVar3[0x6c] = (ATCWaypoint)0x0;
    pAVar3[0x70] = (ATCWaypoint)0x0;
    pAVar3[0x74] = (ATCWaypoint)0x0;
    pAVar3[0x78] = (ATCWaypoint)0x0;
    pAVar3[0x7c] = (ATCWaypoint)0x0;
    pAVar3[0x80] = (ATCWaypoint)0x0;
    pAVar3[0x50] = (ATCWaypoint)0x0;
    *(undefined8 *)(pAVar3 + 0x88) = 0;
    *(undefined8 *)(pAVar3 + 0x90) = 0;
    *(undefined4 *)(pAVar3 + 0x98) = 0;
    *(undefined8 *)(pAVar3 + 0xa0) = 0;
    *(undefined8 *)(pAVar3 + 0xa8) = 0;
    *(undefined8 *)(pAVar3 + 0x40) = uVar1;
    *(undefined8 *)(pAVar3 + 0x48) = uVar2;
    polar_wrap<units::value<double,units::scale<units::compose<units::units::m,units::pow<units::units::m,_1,1>>,180000000,3141593>>>
              (pAVar3 + 0x48,pAVar3 + 0x40);
    *param_2 = pAVar3;
    *param_3 = pAVar3;
  }
  else if (*(undefined8 **)(param_1 + 8) != local_38) {
    lVar7 = 0;
    uVar6 = 0;
    puVar4 = (undefined8 *)0x0;
    do {
      while( true ) {
        pAVar3 = operator_new(0xb0);
        uVar1 = *(undefined8 *)((long)local_38 + lVar7);
        uVar2 = ((undefined8 *)((long)local_38 + lVar7))[1];
        *(undefined8 *)(pAVar3 + 0x28) = 0;
        *(undefined8 *)(pAVar3 + 0x30) = 0;
        *(undefined8 *)(pAVar3 + 0x10) = 0;
        *(undefined8 *)(pAVar3 + 0x18) = 0;
        *(undefined8 *)pAVar3 = 0;
        *(undefined8 *)(pAVar3 + 8) = 0;
        *(undefined8 *)(pAVar3 + 0x1e) = 0;
        *(undefined8 *)(pAVar3 + 0x38) = 0xbf800000bf800000;
        pAVar3[0x54] = (ATCWaypoint)0x0;
        pAVar3[0x58] = (ATCWaypoint)0x0;
        pAVar3[0x5c] = (ATCWaypoint)0x0;
        pAVar3[0x60] = (ATCWaypoint)0x0;
        pAVar3[100] = (ATCWaypoint)0x0;
        pAVar3[0x68] = (ATCWaypoint)0x0;
        pAVar3[0x6c] = (ATCWaypoint)0x0;
        pAVar3[0x70] = (ATCWaypoint)0x0;
        pAVar3[0x74] = (ATCWaypoint)0x0;
        pAVar3[0x78] = (ATCWaypoint)0x0;
        pAVar3[0x7c] = (ATCWaypoint)0x0;
        pAVar3[0x80] = (ATCWaypoint)0x0;
        pAVar3[0x50] = (ATCWaypoint)0x0;
        *(undefined8 *)(pAVar3 + 0x88) = 0;
        *(undefined8 *)(pAVar3 + 0x90) = 0;
        *(undefined4 *)(pAVar3 + 0x98) = 0;
        *(undefined8 *)(pAVar3 + 0xa0) = 0;
        *(undefined8 *)(pAVar3 + 0xa8) = 0;
        *(undefined8 *)(pAVar3 + 0x40) = uVar1;
        *(undefined8 *)(pAVar3 + 0x48) = uVar2;
        polar_wrap<units::value<double,units::scale<units::compose<units::units::m,units::pow<units::units::m,_1,1>>,180000000,3141593>>>
                  (pAVar3 + 0x48,pAVar3 + 0x40);
        if (uVar6 == 0) {
          *param_2 = pAVar3;
        }
        if (puVar4 != (undefined8 *)0x0) {
          puVar4[0x11] = pAVar3;
          *(undefined8 **)(pAVar3 + 0x88) = puVar4;
        }
        local_38 = *(undefined8 **)param_1;
        uVar5 = *(long *)(param_1 + 8) - (long)local_38 >> 4;
        if (uVar6 == uVar5 - 1) break;
        puVar4 = operator_new(0x100);
        uVar1 = *(undefined8 *)(this + 0x10);
        *puVar4 = 0;
        puVar4[1] = 0;
        *(undefined4 *)(puVar4 + 2) = 0;
        puVar4[3] = 0;
        puVar4[4] = 0;
        *(undefined1 *)(puVar4 + 5) = 0;
        puVar4[0xe] = 0;
        puVar4[0xf] = 0;
        puVar4[0xc] = 0;
        puVar4[0xd] = 0;
        puVar4[10] = 0;
        puVar4[0xb] = 0;
        puVar4[8] = 0;
        puVar4[9] = 0;
        puVar4[6] = 0;
        puVar4[7] = 0;
        *(undefined4 *)(puVar4 + 0x10) = 0xfffffffe;
        *(undefined2 *)((long)puVar4 + 0x84) = 0;
        puVar4[0x11] = 0;
        puVar4[0x13] = uVar1;
        puVar4[0x14] = 0;
        *(undefined1 *)(puVar4 + 0x15) = 0;
        *(undefined1 *)(puVar4 + 0x16) = 0;
        *(undefined4 *)(puVar4 + 0x17) = 0xffffffff;
        *(undefined1 *)((long)puVar4 + 0xbc) = 0;
        *(undefined1 *)(puVar4 + 0x18) = 0;
        *(undefined1 *)((long)puVar4 + 0xc4) = 0;
        *(undefined1 *)(puVar4 + 0x19) = 0;
        *(undefined4 *)((long)puVar4 + 0xcc) = 0xffffffff;
        *(undefined1 *)(puVar4 + 0x1a) = 0;
        *(undefined1 *)((long)puVar4 + 0xd4) = 0;
        *(undefined1 *)(puVar4 + 0x1b) = 0;
        *(undefined1 *)((long)puVar4 + 0xdc) = 0;
        *(undefined1 *)(puVar4 + 0x1c) = 0;
        *(undefined1 *)((long)puVar4 + 0xe4) = 0;
        *(undefined1 *)(puVar4 + 0x1d) = 0;
        *(undefined1 *)((long)puVar4 + 0xec) = 0;
        *(undefined1 *)(puVar4 + 0x1e) = 0;
        puVar4[0x1f] = 0;
        *(undefined8 **)(pAVar3 + 0x90) = puVar4;
        puVar4[0x12] = pAVar3;
        uVar6 = uVar6 + 1;
        lVar7 = lVar7 + 0x10;
        if (uVar5 <= uVar6) {
          return;
        }
      }
      *param_3 = pAVar3;
      local_38 = *(undefined8 **)param_1;
      uVar6 = uVar6 + 1;
      lVar7 = lVar7 + 0x10;
    } while (uVar6 < (ulong)(*(long *)(param_1 + 8) - (long)local_38 >> 4));
  }
  return;
}


// 001d57c0  ATCFlightSegment::~ATCFlightSegment

/* ATCFlightSegment::~ATCFlightSegment() */

void __thiscall ATCFlightSegment::~ATCFlightSegment(ATCFlightSegment *this)

{
  ~ATCFlightSegment(this);
  return;
}


// 001d57d0  ATCFlightRoute::Splice

/* ATCFlightRoute::Splice(ATCWaypoint*, ATCWaypoint*, std::vector<GeoPoint2D,
   std::allocator<GeoPoint2D> > const&) */

void __thiscall
ATCFlightRoute::Splice
          (ATCFlightRoute *this,ATCWaypoint *param_1,ATCWaypoint *param_2,vector *param_3)

{
  byte *pbVar1;
  undefined8 uVar2;
  ATCFlightRoute *pAVar3;
  undefined8 *puVar4;
  undefined8 *puVar5;
  ATCFlightSegment *this_00;
  ATCFlightSegment *pAVar6;
  ATCWaypoint *local_58;
  ATCWaypoint *local_50;
  ATCWaypoint *local_48;
  ATCWaypoint *local_40;
  ATCFlightRoute *local_38;
  
  local_40 = param_1 + 0x90;
  this_00 = *(ATCFlightSegment **)(param_1 + 0x90);
  *(undefined8 *)(param_1 + 0x90) = 0;
  *(undefined8 *)(this_00 + 0x90) = 0;
  *(undefined8 *)(*(long *)(param_2 + 0x88) + 0x88) = 0;
  *(undefined8 *)(param_2 + 0x88) = 0;
  local_48 = param_2;
  local_38 = this;
  do {
    pbVar1 = *(byte **)(this_00 + 0x88);
    if (pbVar1 == (byte *)0x0) {
      pAVar6 = (ATCFlightSegment *)0x0;
    }
    else {
      pAVar6 = *(ATCFlightSegment **)(pbVar1 + 0x90);
      if ((*pbVar1 & 1) != 0) {
        operator_delete(*(void **)(pbVar1 + 0x10));
      }
      operator_delete(pbVar1);
    }
    ATCFlightSegment::~ATCFlightSegment(this_00);
    operator_delete(this_00);
    pAVar3 = local_38;
    this_00 = pAVar6;
  } while (pAVar6 != (ATCFlightSegment *)0x0);
  if (*(long *)param_3 == *(long *)(param_3 + 8)) {
    puVar5 = operator_new(0x100);
    uVar2 = *(undefined8 *)(local_38 + 0x10);
    *puVar5 = 0;
    puVar5[1] = 0;
    *(undefined4 *)(puVar5 + 2) = 0;
    puVar5[3] = 0;
    puVar5[4] = 0;
    *(undefined1 *)(puVar5 + 5) = 0;
    puVar5[0xe] = 0;
    puVar5[0xf] = 0;
    puVar5[0xc] = 0;
    puVar5[0xd] = 0;
    puVar5[10] = 0;
    puVar5[0xb] = 0;
    puVar5[8] = 0;
    puVar5[9] = 0;
    puVar5[6] = 0;
    puVar5[7] = 0;
    *(undefined4 *)(puVar5 + 0x10) = 0xfffffffe;
    *(undefined2 *)((long)puVar5 + 0x84) = 0;
    puVar5[0x13] = uVar2;
    puVar5[0x14] = 0;
    *(undefined1 *)(puVar5 + 0x15) = 0;
    *(undefined1 *)(puVar5 + 0x16) = 0;
    *(undefined4 *)(puVar5 + 0x17) = 0xffffffff;
    *(undefined1 *)((long)puVar5 + 0xbc) = 0;
    *(undefined1 *)(puVar5 + 0x18) = 0;
    *(undefined1 *)((long)puVar5 + 0xc4) = 0;
    *(undefined1 *)(puVar5 + 0x19) = 0;
    *(undefined4 *)((long)puVar5 + 0xcc) = 0xffffffff;
    *(undefined1 *)(puVar5 + 0x1a) = 0;
    *(undefined1 *)((long)puVar5 + 0xd4) = 0;
    *(undefined1 *)(puVar5 + 0x1b) = 0;
    *(undefined1 *)((long)puVar5 + 0xdc) = 0;
    *(undefined1 *)(puVar5 + 0x1c) = 0;
    *(undefined1 *)((long)puVar5 + 0xe4) = 0;
    *(undefined1 *)(puVar5 + 0x1d) = 0;
    *(undefined1 *)((long)puVar5 + 0xec) = 0;
    *(undefined1 *)(puVar5 + 0x1e) = 0;
    puVar5[0x1f] = 0;
    local_50 = param_1;
  }
  else {
    CreateChain(local_38,param_3,&local_58,&local_50);
    puVar4 = operator_new(0x100);
    uVar2 = *(undefined8 *)(pAVar3 + 0x10);
    *puVar4 = 0;
    puVar4[1] = 0;
    *(undefined4 *)(puVar4 + 2) = 0;
    puVar4[3] = 0;
    puVar4[4] = 0;
    *(undefined1 *)(puVar4 + 5) = 0;
    puVar4[0xe] = 0;
    puVar4[0xf] = 0;
    puVar4[0xc] = 0;
    puVar4[0xd] = 0;
    puVar4[10] = 0;
    puVar4[0xb] = 0;
    puVar4[8] = 0;
    puVar4[9] = 0;
    puVar4[6] = 0;
    puVar4[7] = 0;
    *(undefined4 *)(puVar4 + 0x10) = 0xfffffffe;
    *(undefined2 *)((long)puVar4 + 0x84) = 0;
    puVar4[0x11] = 0;
    puVar4[0x12] = 0;
    puVar4[0x13] = uVar2;
    puVar4[0x14] = 0;
    *(undefined1 *)(puVar4 + 0x15) = 0;
    *(undefined1 *)(puVar4 + 0x16) = 0;
    *(undefined4 *)(puVar4 + 0x17) = 0xffffffff;
    *(undefined1 *)((long)puVar4 + 0xbc) = 0;
    *(undefined1 *)(puVar4 + 0x18) = 0;
    *(undefined1 *)((long)puVar4 + 0xc4) = 0;
    *(undefined1 *)(puVar4 + 0x19) = 0;
    *(undefined4 *)((long)puVar4 + 0xcc) = 0xffffffff;
    *(undefined1 *)(puVar4 + 0x1a) = 0;
    *(undefined1 *)((long)puVar4 + 0xd4) = 0;
    *(undefined1 *)(puVar4 + 0x1b) = 0;
    *(undefined1 *)((long)puVar4 + 0xdc) = 0;
    *(undefined1 *)(puVar4 + 0x1c) = 0;
    *(undefined1 *)((long)puVar4 + 0xe4) = 0;
    *(undefined1 *)(puVar4 + 0x1d) = 0;
    *(undefined1 *)((long)puVar4 + 0xec) = 0;
    *(undefined1 *)(puVar4 + 0x1e) = 0;
    puVar4[0x1f] = 0;
    puVar5 = operator_new(0x100);
    *puVar5 = 0;
    puVar5[1] = 0;
    *(undefined4 *)(puVar5 + 2) = 0;
    puVar5[3] = 0;
    puVar5[4] = 0;
    *(undefined1 *)(puVar5 + 5) = 0;
    puVar5[6] = 0;
    puVar5[7] = 0;
    puVar5[8] = 0;
    puVar5[9] = 0;
    puVar5[10] = 0;
    puVar5[0xb] = 0;
    puVar5[0xc] = 0;
    puVar5[0xd] = 0;
    puVar5[0xe] = 0;
    puVar5[0xf] = 0;
    *(undefined4 *)(puVar5 + 0x10) = 0xfffffffe;
    *(undefined2 *)((long)puVar5 + 0x84) = 0;
    puVar5[0x13] = uVar2;
    puVar5[0x14] = 0;
    *(undefined1 *)(puVar5 + 0x15) = 0;
    *(undefined1 *)(puVar5 + 0x16) = 0;
    *(undefined4 *)(puVar5 + 0x17) = 0xffffffff;
    *(undefined1 *)((long)puVar5 + 0xbc) = 0;
    *(undefined1 *)(puVar5 + 0x18) = 0;
    *(undefined1 *)((long)puVar5 + 0xc4) = 0;
    *(undefined1 *)(puVar5 + 0x19) = 0;
    *(undefined4 *)((long)puVar5 + 0xcc) = 0xffffffff;
    *(undefined1 *)(puVar5 + 0x1a) = 0;
    *(undefined1 *)((long)puVar5 + 0xd4) = 0;
    *(undefined1 *)(puVar5 + 0x1b) = 0;
    *(undefined1 *)((long)puVar5 + 0xdc) = 0;
    *(undefined1 *)(puVar5 + 0x1c) = 0;
    *(undefined1 *)((long)puVar5 + 0xe4) = 0;
    *(undefined1 *)(puVar5 + 0x1d) = 0;
    *(undefined1 *)((long)puVar5 + 0xec) = 0;
    *(undefined1 *)(puVar5 + 0x1e) = 0;
    puVar5[0x1f] = 0;
    *(undefined8 **)(param_1 + 0x90) = puVar4;
    puVar4[0x12] = param_1;
    puVar4[0x11] = local_58;
    *(undefined8 **)(local_58 + 0x88) = puVar4;
    local_40 = local_50 + 0x90;
  }
  *(undefined8 **)local_40 = puVar5;
  puVar5[0x12] = local_50;
  puVar5[0x11] = local_48;
  *(undefined8 **)(local_48 + 0x88) = puVar5;
  return;
}


// 001d5be0  ATCFlightRoute::InsertFront

/* ATCFlightRoute::InsertFront(std::vector<GeoPoint2D, std::allocator<GeoPoint2D> > const&) */

void __thiscall ATCFlightRoute::InsertFront(ATCFlightRoute *this,vector *param_1)

{
  ATCWaypoint *local_20;
  ATCWaypoint *local_18;
  
  if (*(ATCWaypoint **)this != (ATCWaypoint *)0x0) {
    InsertBefore(this,*(ATCWaypoint **)this,param_1);
    return;
  }
  CreateChain(this,param_1,&local_20,&local_18);
  *(ATCWaypoint **)this = local_20;
  *(ATCWaypoint **)(this + 8) = local_18;
  return;
}


// 001d5c40  ATCFlightRoute::InsertBefore

/* ATCFlightRoute::InsertBefore(ATCWaypoint*, std::vector<GeoPoint2D, std::allocator<GeoPoint2D> >
   const&) */

void __thiscall
ATCFlightRoute::InsertBefore(ATCFlightRoute *this,ATCWaypoint *param_1,vector *param_2)

{
  long lVar1;
  undefined8 uVar2;
  undefined8 *puVar3;
  ATCWaypoint *local_28;
  ATCWaypoint *local_20;
  
  CreateChain(this,param_2,&local_28,&local_20);
  if (*(ATCWaypoint **)this == param_1) {
    puVar3 = operator_new(0x100);
    uVar2 = *(undefined8 *)(this + 0x10);
    *puVar3 = 0;
    puVar3[1] = 0;
    *(undefined4 *)(puVar3 + 2) = 0;
    puVar3[3] = 0;
    puVar3[4] = 0;
    *(undefined1 *)(puVar3 + 5) = 0;
    puVar3[0xe] = 0;
    puVar3[0xf] = 0;
    puVar3[0xc] = 0;
    puVar3[0xd] = 0;
    puVar3[10] = 0;
    puVar3[0xb] = 0;
    puVar3[8] = 0;
    puVar3[9] = 0;
    puVar3[6] = 0;
    puVar3[7] = 0;
    *(undefined4 *)(puVar3 + 0x10) = 0xfffffffe;
    *(undefined2 *)((long)puVar3 + 0x84) = 0;
    puVar3[0x13] = uVar2;
    puVar3[0x14] = 0;
    *(undefined1 *)(puVar3 + 0x15) = 0;
    *(undefined1 *)(puVar3 + 0x16) = 0;
    *(undefined4 *)(puVar3 + 0x17) = 0xffffffff;
    *(undefined1 *)((long)puVar3 + 0xbc) = 0;
    *(undefined1 *)(puVar3 + 0x18) = 0;
    *(undefined1 *)((long)puVar3 + 0xc4) = 0;
    *(undefined1 *)(puVar3 + 0x19) = 0;
    *(undefined4 *)((long)puVar3 + 0xcc) = 0xffffffff;
    *(undefined1 *)(puVar3 + 0x1a) = 0;
    *(undefined1 *)((long)puVar3 + 0xd4) = 0;
    *(undefined1 *)(puVar3 + 0x1b) = 0;
    *(undefined1 *)((long)puVar3 + 0xdc) = 0;
    *(undefined1 *)(puVar3 + 0x1c) = 0;
    *(undefined1 *)((long)puVar3 + 0xe4) = 0;
    *(undefined1 *)(puVar3 + 0x1d) = 0;
    *(undefined1 *)((long)puVar3 + 0xec) = 0;
    *(undefined1 *)(puVar3 + 0x1e) = 0;
    puVar3[0x1f] = 0;
    *(undefined8 **)(local_20 + 0x90) = puVar3;
    puVar3[0x12] = local_20;
    puVar3[0x11] = param_1;
    *(undefined8 **)(param_1 + 0x88) = puVar3;
    *(ATCWaypoint **)this = local_28;
  }
  else {
    lVar1 = *(long *)(param_1 + 0x88);
    *(undefined8 *)(param_1 + 0x88) = 0;
    *(ATCWaypoint **)(lVar1 + 0x88) = local_28;
    *(long *)(local_28 + 0x88) = lVar1;
    puVar3 = operator_new(0x100);
    uVar2 = *(undefined8 *)(this + 0x10);
    *puVar3 = 0;
    puVar3[1] = 0;
    *(undefined4 *)(puVar3 + 2) = 0;
    puVar3[3] = 0;
    puVar3[4] = 0;
    *(undefined1 *)(puVar3 + 5) = 0;
    puVar3[0xe] = 0;
    puVar3[0xf] = 0;
    puVar3[0xc] = 0;
    puVar3[0xd] = 0;
    puVar3[10] = 0;
    puVar3[0xb] = 0;
    puVar3[8] = 0;
    puVar3[9] = 0;
    puVar3[6] = 0;
    puVar3[7] = 0;
    *(undefined4 *)(puVar3 + 0x10) = 0xfffffffe;
    *(undefined2 *)((long)puVar3 + 0x84) = 0;
    puVar3[0x13] = uVar2;
    puVar3[0x14] = 0;
    *(undefined1 *)(puVar3 + 0x15) = 0;
    *(undefined1 *)(puVar3 + 0x16) = 0;
    *(undefined4 *)(puVar3 + 0x17) = 0xffffffff;
    *(undefined1 *)((long)puVar3 + 0xbc) = 0;
    *(undefined1 *)(puVar3 + 0x18) = 0;
    *(undefined1 *)((long)puVar3 + 0xc4) = 0;
    *(undefined1 *)(puVar3 + 0x19) = 0;
    *(undefined4 *)((long)puVar3 + 0xcc) = 0xffffffff;
    *(undefined1 *)(puVar3 + 0x1a) = 0;
    *(undefined1 *)((long)puVar3 + 0xd4) = 0;
    *(undefined1 *)(puVar3 + 0x1b) = 0;
    *(undefined1 *)((long)puVar3 + 0xdc) = 0;
    *(undefined1 *)(puVar3 + 0x1c) = 0;
    *(undefined1 *)((long)puVar3 + 0xe4) = 0;
    *(undefined1 *)(puVar3 + 0x1d) = 0;
    *(undefined1 *)((long)puVar3 + 0xec) = 0;
    *(undefined1 *)(puVar3 + 0x1e) = 0;
    puVar3[0x1f] = 0;
    *(undefined8 **)(local_20 + 0x90) = puVar3;
    puVar3[0x12] = local_20;
    puVar3[0x11] = param_1;
    *(undefined8 **)(param_1 + 0x88) = puVar3;
  }
  return;
}


// 001d5eb0  ATCFlightRoute::InsertBack

/* ATCFlightRoute::InsertBack(std::vector<GeoPoint2D, std::allocator<GeoPoint2D> > const&) */

void __thiscall ATCFlightRoute::InsertBack(ATCFlightRoute *this,vector *param_1)

{
  ATCWaypoint *local_20;
  ATCWaypoint *local_18;
  
  if (*(ATCWaypoint **)(this + 8) != (ATCWaypoint *)0x0) {
    InsertAfter(this,*(ATCWaypoint **)(this + 8),param_1);
    return;
  }
  CreateChain(this,param_1,&local_20,&local_18);
  *(ATCWaypoint **)this = local_20;
  *(ATCWaypoint **)(this + 8) = local_18;
  return;
}


// 001d5f10  ATCFlightRoute::InsertAfter

/* ATCFlightRoute::InsertAfter(ATCWaypoint*, std::vector<GeoPoint2D, std::allocator<GeoPoint2D> >
   const&) */

void __thiscall
ATCFlightRoute::InsertAfter(ATCFlightRoute *this,ATCWaypoint *param_1,vector *param_2)

{
  long lVar1;
  undefined8 uVar2;
  undefined8 *puVar3;
  ATCWaypoint *local_30;
  ATCWaypoint *local_28;
  
  CreateChain(this,param_2,&local_30,&local_28);
  if (*(ATCWaypoint **)(this + 8) == param_1) {
    puVar3 = operator_new(0x100);
    uVar2 = *(undefined8 *)(this + 0x10);
    *puVar3 = 0;
    puVar3[1] = 0;
    *(undefined4 *)(puVar3 + 2) = 0;
    puVar3[3] = 0;
    puVar3[4] = 0;
    *(undefined1 *)(puVar3 + 5) = 0;
    puVar3[0xe] = 0;
    puVar3[0xf] = 0;
    puVar3[0xc] = 0;
    puVar3[0xd] = 0;
    puVar3[10] = 0;
    puVar3[0xb] = 0;
    puVar3[8] = 0;
    puVar3[9] = 0;
    puVar3[6] = 0;
    puVar3[7] = 0;
    *(undefined4 *)(puVar3 + 0x10) = 0xfffffffe;
    *(undefined2 *)((long)puVar3 + 0x84) = 0;
    puVar3[0x13] = uVar2;
    puVar3[0x14] = 0;
    *(undefined1 *)(puVar3 + 0x15) = 0;
    *(undefined1 *)(puVar3 + 0x16) = 0;
    *(undefined4 *)(puVar3 + 0x17) = 0xffffffff;
    *(undefined1 *)((long)puVar3 + 0xbc) = 0;
    *(undefined1 *)(puVar3 + 0x18) = 0;
    *(undefined1 *)((long)puVar3 + 0xc4) = 0;
    *(undefined1 *)(puVar3 + 0x19) = 0;
    *(undefined4 *)((long)puVar3 + 0xcc) = 0xffffffff;
    *(undefined1 *)(puVar3 + 0x1a) = 0;
    *(undefined1 *)((long)puVar3 + 0xd4) = 0;
    *(undefined1 *)(puVar3 + 0x1b) = 0;
    *(undefined1 *)((long)puVar3 + 0xdc) = 0;
    *(undefined1 *)(puVar3 + 0x1c) = 0;
    *(undefined1 *)((long)puVar3 + 0xe4) = 0;
    *(undefined1 *)(puVar3 + 0x1d) = 0;
    *(undefined1 *)((long)puVar3 + 0xec) = 0;
    *(undefined1 *)(puVar3 + 0x1e) = 0;
    puVar3[0x1f] = 0;
    *(undefined8 **)(param_1 + 0x90) = puVar3;
    puVar3[0x12] = param_1;
    puVar3[0x11] = local_30;
    *(undefined8 **)(local_30 + 0x88) = puVar3;
    *(ATCWaypoint **)(this + 8) = local_28;
  }
  else {
    lVar1 = *(long *)(param_1 + 0x90);
    *(undefined8 *)(param_1 + 0x90) = 0;
    *(undefined8 *)(lVar1 + 0x90) = 0;
    puVar3 = operator_new(0x100);
    uVar2 = *(undefined8 *)(this + 0x10);
    *puVar3 = 0;
    puVar3[1] = 0;
    *(undefined4 *)(puVar3 + 2) = 0;
    puVar3[3] = 0;
    puVar3[4] = 0;
    *(undefined1 *)(puVar3 + 5) = 0;
    puVar3[0xe] = 0;
    puVar3[0xf] = 0;
    puVar3[0xc] = 0;
    puVar3[0xd] = 0;
    puVar3[10] = 0;
    puVar3[0xb] = 0;
    puVar3[8] = 0;
    puVar3[9] = 0;
    puVar3[6] = 0;
    puVar3[7] = 0;
    *(undefined4 *)(puVar3 + 0x10) = 0xfffffffe;
    *(undefined2 *)((long)puVar3 + 0x84) = 0;
    puVar3[0x13] = uVar2;
    puVar3[0x14] = 0;
    *(undefined1 *)(puVar3 + 0x15) = 0;
    *(undefined1 *)(puVar3 + 0x16) = 0;
    *(undefined4 *)(puVar3 + 0x17) = 0xffffffff;
    *(undefined1 *)((long)puVar3 + 0xbc) = 0;
    *(undefined1 *)(puVar3 + 0x18) = 0;
    *(undefined1 *)((long)puVar3 + 0xc4) = 0;
    *(undefined1 *)(puVar3 + 0x19) = 0;
    *(undefined4 *)((long)puVar3 + 0xcc) = 0xffffffff;
    *(undefined1 *)(puVar3 + 0x1a) = 0;
    *(undefined1 *)((long)puVar3 + 0xd4) = 0;
    *(undefined1 *)(puVar3 + 0x1b) = 0;
    *(undefined1 *)((long)puVar3 + 0xdc) = 0;
    *(undefined1 *)(puVar3 + 0x1c) = 0;
    *(undefined1 *)((long)puVar3 + 0xe4) = 0;
    *(undefined1 *)(puVar3 + 0x1d) = 0;
    *(undefined1 *)((long)puVar3 + 0xec) = 0;
    *(undefined1 *)(puVar3 + 0x1e) = 0;
    puVar3[0x1f] = 0;
    *(undefined8 **)(param_1 + 0x90) = puVar3;
    puVar3[0x12] = param_1;
    puVar3[0x11] = local_30;
    *(undefined8 **)(local_30 + 0x88) = puVar3;
    *(long *)(local_28 + 0x90) = lVar1;
    *(ATCWaypoint **)(lVar1 + 0x90) = local_28;
  }
  return;
}


// 001d61f0  ATCFlightRoute::Split

/* ATCFlightRoute::Split(ATCFlightSegment*, GeoPoint2D const&) */

undefined8 * __thiscall
ATCFlightRoute::Split(ATCFlightRoute *this,ATCFlightSegment *param_1,GeoPoint2D *param_2)

{
  long lVar1;
  undefined8 uVar2;
  undefined8 uVar3;
  undefined8 *puVar4;
  ATCFlightSegment *this_00;
  
  lVar1 = *(long *)(param_1 + 0x88);
  puVar4 = operator_new(0xb0);
  uVar2 = *(undefined8 *)param_2;
  uVar3 = *(undefined8 *)(param_2 + 8);
  puVar4[5] = 0;
  puVar4[6] = 0;
  puVar4[2] = 0;
  puVar4[3] = 0;
  *puVar4 = 0;
  puVar4[1] = 0;
  *(undefined8 *)((long)puVar4 + 0x1e) = 0;
  puVar4[7] = 0xbf800000bf800000;
  *(undefined1 *)((long)puVar4 + 0x54) = 0;
  *(undefined1 *)(puVar4 + 0xb) = 0;
  *(undefined1 *)((long)puVar4 + 0x5c) = 0;
  *(undefined1 *)(puVar4 + 0xc) = 0;
  *(undefined1 *)((long)puVar4 + 100) = 0;
  *(undefined1 *)(puVar4 + 0xd) = 0;
  *(undefined1 *)((long)puVar4 + 0x6c) = 0;
  *(undefined1 *)(puVar4 + 0xe) = 0;
  *(undefined1 *)((long)puVar4 + 0x74) = 0;
  *(undefined1 *)(puVar4 + 0xf) = 0;
  *(undefined1 *)((long)puVar4 + 0x7c) = 0;
  *(undefined1 *)(puVar4 + 0x10) = 0;
  *(undefined1 *)(puVar4 + 10) = 0;
  puVar4[0x11] = 0;
  puVar4[0x12] = 0;
  *(undefined4 *)(puVar4 + 0x13) = 0;
  puVar4[0x14] = 0;
  puVar4[0x15] = 0;
  puVar4[8] = uVar2;
  puVar4[9] = uVar3;
  polar_wrap<units::value<double,units::scale<units::compose<units::units::m,units::pow<units::units::m,_1,1>>,180000000,3141593>>>
            ((value *)(puVar4 + 9),(value *)(puVar4 + 8));
  this_00 = operator_new(0x100);
  ATCFlightSegment::ATCFlightSegment(this_00,param_1);
  *(undefined8 **)(param_1 + 0x88) = puVar4;
  puVar4[0x11] = param_1;
  puVar4[0x12] = this_00;
  *(undefined8 **)(this_00 + 0x90) = puVar4;
  *(long *)(this_00 + 0x88) = lVar1;
  *(ATCFlightSegment **)(lVar1 + 0x88) = this_00;
  return puVar4;
}


// 001d6320  ATCFlightRoute::TrimBefore

/* ATCFlightRoute::TrimBefore(ATCWaypoint*) */

void __thiscall ATCFlightRoute::TrimBefore(ATCFlightRoute *this,ATCWaypoint *param_1)

{
  ATCWaypoint AVar1;
  ATCWaypoint *pAVar2;
  ATCFlightSegment *this_00;
  ATCWaypoint *pAVar3;
  
  pAVar2 = *(ATCWaypoint **)this;
  if (pAVar2 != param_1) {
    *(undefined8 *)(*(long *)(param_1 + 0x88) + 0x88) = 0;
    *(undefined8 *)(param_1 + 0x88) = 0;
    while (pAVar2 != (ATCWaypoint *)0x0) {
      this_00 = *(ATCFlightSegment **)(pAVar2 + 0x90);
      if (this_00 == (ATCFlightSegment *)0x0) {
        pAVar3 = (ATCWaypoint *)0x0;
        AVar1 = *pAVar2;
      }
      else {
        pAVar3 = *(ATCWaypoint **)(this_00 + 0x88);
        ATCFlightSegment::~ATCFlightSegment(this_00);
        operator_delete(this_00);
        AVar1 = *pAVar2;
      }
      if (((byte)AVar1 & 1) != 0) {
        operator_delete(*(void **)(pAVar2 + 0x10));
      }
      operator_delete(pAVar2);
      pAVar2 = pAVar3;
    }
    *(ATCWaypoint **)this = param_1;
  }
  return;
}


// 001d63d0  ATCFlightRoute::TrimAfter

/* ATCFlightRoute::TrimAfter(ATCWaypoint*) */

void __thiscall ATCFlightRoute::TrimAfter(ATCFlightRoute *this,ATCWaypoint *param_1)

{
  byte *pbVar1;
  ATCFlightSegment *this_00;
  ATCFlightSegment *pAVar2;
  
  if (*(ATCWaypoint **)(this + 8) != param_1) {
    this_00 = *(ATCFlightSegment **)(param_1 + 0x90);
    *(undefined8 *)(param_1 + 0x90) = 0;
    *(undefined8 *)(this_00 + 0x90) = 0;
    do {
      pbVar1 = *(byte **)(this_00 + 0x88);
      if (pbVar1 == (byte *)0x0) {
        pAVar2 = (ATCFlightSegment *)0x0;
      }
      else {
        pAVar2 = *(ATCFlightSegment **)(pbVar1 + 0x90);
        if ((*pbVar1 & 1) != 0) {
          operator_delete(*(void **)(pbVar1 + 0x10));
        }
        operator_delete(pbVar1);
      }
      ATCFlightSegment::~ATCFlightSegment(this_00);
      operator_delete(this_00);
      this_00 = pAVar2;
    } while (pAVar2 != (ATCFlightSegment *)0x0);
    *(ATCWaypoint **)(this + 8) = param_1;
  }
  return;
}


// 001d6480  ATCFlightRoute::Remove

/* ATCFlightRoute::Remove(ATCWaypoint*) */

void __thiscall ATCFlightRoute::Remove(ATCFlightRoute *this,ATCWaypoint *param_1)

{
  ATCWaypoint AVar1;
  long lVar2;
  byte *pbVar3;
  ATCWaypoint *pAVar4;
  ATCWaypoint *pAVar5;
  ATCWaypoint *pAVar6;
  ATCFlightSegment *pAVar7;
  ATCFlightSegment *pAVar8;
  long lVar9;
  
  if (*(ATCWaypoint **)(this + 8) == param_1) {
    if (*(long *)(param_1 + 0x88) == 0) {
      pAVar6 = (ATCWaypoint *)0x0;
      if (param_1 == (ATCWaypoint *)0x0) {
        return;
      }
    }
    else {
      pAVar6 = *(ATCWaypoint **)(*(long *)(param_1 + 0x88) + 0x90);
      if (pAVar6 == param_1) {
        return;
      }
    }
    pAVar7 = *(ATCFlightSegment **)(pAVar6 + 0x90);
    *(undefined8 *)(pAVar6 + 0x90) = 0;
    *(undefined8 *)(pAVar7 + 0x90) = 0;
    do {
      pbVar3 = *(byte **)(pAVar7 + 0x88);
      if (pbVar3 == (byte *)0x0) {
        pAVar8 = (ATCFlightSegment *)0x0;
      }
      else {
        pAVar8 = *(ATCFlightSegment **)(pbVar3 + 0x90);
        if ((*pbVar3 & 1) != 0) {
          operator_delete(*(void **)(pbVar3 + 0x10));
        }
        operator_delete(pbVar3);
      }
      ATCFlightSegment::~ATCFlightSegment(pAVar7);
      operator_delete(pAVar7);
      pAVar7 = pAVar8;
    } while (pAVar8 != (ATCFlightSegment *)0x0);
    *(ATCWaypoint **)(this + 8) = pAVar6;
  }
  else {
    pAVar7 = *(ATCFlightSegment **)(param_1 + 0x90);
    if (*(ATCWaypoint **)this != param_1) {
      if (pAVar7 == (ATCFlightSegment *)0x0) {
        lVar9 = 0;
      }
      else {
        lVar9 = *(long *)(pAVar7 + 0x88);
      }
      lVar2 = *(long *)(param_1 + 0x88);
      *(undefined8 *)(pAVar7 + 0x88) = 0;
      *(undefined8 *)(lVar9 + 0x88) = 0;
      if (pAVar7 == (ATCFlightSegment *)0x0) goto LAB_001d6563;
      do {
        pAVar6 = *(ATCWaypoint **)(pAVar7 + 0x88);
        ATCFlightSegment::~ATCFlightSegment(pAVar7);
        operator_delete(pAVar7);
        AVar1 = *param_1;
        pAVar4 = param_1;
        while( true ) {
          param_1 = pAVar6;
          if (((byte)AVar1 & 1) != 0) {
            operator_delete(*(void **)(pAVar4 + 0x10));
          }
          operator_delete(pAVar4);
          if (param_1 == (ATCWaypoint *)0x0) {
            *(long *)(lVar2 + 0x88) = lVar9;
            *(long *)(lVar9 + 0x88) = lVar2;
            return;
          }
          pAVar7 = *(ATCFlightSegment **)(param_1 + 0x90);
          if (pAVar7 != (ATCFlightSegment *)0x0) break;
LAB_001d6563:
          AVar1 = *param_1;
          pAVar6 = (ATCWaypoint *)0x0;
          pAVar4 = param_1;
        }
      } while( true );
    }
    if (pAVar7 == (ATCFlightSegment *)0x0) {
      pAVar6 = (ATCWaypoint *)0x0;
      if (param_1 != (ATCWaypoint *)0x0) goto LAB_001d6615;
    }
    else {
      pAVar6 = *(ATCWaypoint **)(pAVar7 + 0x88);
      if (pAVar6 != param_1) {
LAB_001d6615:
        *(undefined8 *)(*(long *)(pAVar6 + 0x88) + 0x88) = 0;
        *(undefined8 *)(pAVar6 + 0x88) = 0;
        if (pAVar7 == (ATCFlightSegment *)0x0) goto LAB_001d6683;
        do {
          pAVar4 = *(ATCWaypoint **)(pAVar7 + 0x88);
          ATCFlightSegment::~ATCFlightSegment(pAVar7);
          operator_delete(pAVar7);
          AVar1 = *param_1;
          pAVar5 = param_1;
          while( true ) {
            param_1 = pAVar4;
            if (((byte)AVar1 & 1) != 0) {
              operator_delete(*(void **)(pAVar5 + 0x10));
            }
            operator_delete(pAVar5);
            if (param_1 == (ATCWaypoint *)0x0) {
              *(ATCWaypoint **)this = pAVar6;
              return;
            }
            pAVar7 = *(ATCFlightSegment **)(param_1 + 0x90);
            if (pAVar7 != (ATCFlightSegment *)0x0) break;
LAB_001d6683:
            AVar1 = *param_1;
            pAVar4 = (ATCWaypoint *)0x0;
            pAVar5 = param_1;
          }
        } while( true );
      }
    }
  }
  return;
}


// 001d66a0  ATCFlightRoute::Split

/* ATCFlightRoute::Split(ATCWaypoint*) */

void __thiscall ATCFlightRoute::Split(ATCFlightRoute *this,ATCWaypoint *param_1)

{
  undefined8 uVar1;
  long lVar2;
  undefined8 uVar3;
  undefined8 uVar4;
  undefined8 uVar5;
  undefined8 uVar6;
  undefined8 uVar7;
  undefined8 uVar8;
  string *this_00;
  undefined8 *puVar9;
  
  this_00 = operator_new(0xb0);
  std::string::string(this_00,(string *)param_1);
  uVar1 = *(undefined8 *)(param_1 + 0x18);
  *(undefined8 *)(this_00 + 0x1e) = *(undefined8 *)(param_1 + 0x1e);
  *(undefined8 *)(this_00 + 0x18) = uVar1;
  uVar1 = *(undefined8 *)(param_1 + 0x30);
  *(undefined8 *)(this_00 + 0x28) = *(undefined8 *)(param_1 + 0x28);
  *(undefined8 *)(this_00 + 0x30) = uVar1;
  *(undefined8 *)(this_00 + 0xa8) = *(undefined8 *)(param_1 + 0xa8);
  uVar1 = *(undefined8 *)(param_1 + 0xa0);
  *(undefined8 *)(this_00 + 0x98) = *(undefined8 *)(param_1 + 0x98);
  *(undefined8 *)(this_00 + 0xa0) = uVar1;
  uVar1 = *(undefined8 *)(param_1 + 0x90);
  *(undefined8 *)(this_00 + 0x88) = *(undefined8 *)(param_1 + 0x88);
  *(undefined8 *)(this_00 + 0x90) = uVar1;
  uVar1 = *(undefined8 *)(param_1 + 0x80);
  *(undefined8 *)(this_00 + 0x78) = *(undefined8 *)(param_1 + 0x78);
  *(undefined8 *)(this_00 + 0x80) = uVar1;
  uVar1 = *(undefined8 *)(param_1 + 0x38);
  uVar3 = *(undefined8 *)(param_1 + 0x40);
  uVar4 = *(undefined8 *)(param_1 + 0x48);
  uVar5 = *(undefined8 *)(param_1 + 0x50);
  uVar6 = *(undefined8 *)(param_1 + 0x58);
  uVar7 = *(undefined8 *)(param_1 + 0x60);
  uVar8 = *(undefined8 *)(param_1 + 0x70);
  *(undefined8 *)(this_00 + 0x68) = *(undefined8 *)(param_1 + 0x68);
  *(undefined8 *)(this_00 + 0x70) = uVar8;
  *(undefined8 *)(this_00 + 0x58) = uVar6;
  *(undefined8 *)(this_00 + 0x60) = uVar7;
  *(undefined8 *)(this_00 + 0x48) = uVar4;
  *(undefined8 *)(this_00 + 0x50) = uVar5;
  *(undefined8 *)(this_00 + 0x38) = uVar1;
  *(undefined8 *)(this_00 + 0x40) = uVar3;
  puVar9 = operator_new(0x100);
  uVar1 = *(undefined8 *)(this + 0x10);
  *puVar9 = 0;
  puVar9[1] = 0;
  *(undefined4 *)(puVar9 + 2) = 0;
  puVar9[3] = 0;
  puVar9[4] = 0;
  *(undefined1 *)(puVar9 + 5) = 0;
  puVar9[0xe] = 0;
  puVar9[0xf] = 0;
  puVar9[0xc] = 0;
  puVar9[0xd] = 0;
  puVar9[10] = 0;
  puVar9[0xb] = 0;
  puVar9[8] = 0;
  puVar9[9] = 0;
  puVar9[6] = 0;
  puVar9[7] = 0;
  *(undefined4 *)(puVar9 + 0x10) = 0xfffffffe;
  *(undefined2 *)((long)puVar9 + 0x84) = 0;
  puVar9[0x11] = 0;
  puVar9[0x12] = 0;
  puVar9[0x13] = uVar1;
  puVar9[0x14] = 0;
  *(undefined1 *)(puVar9 + 0x15) = 0;
  *(undefined1 *)(puVar9 + 0x16) = 0;
  *(undefined4 *)(puVar9 + 0x17) = 0xffffffff;
  *(undefined1 *)((long)puVar9 + 0xbc) = 0;
  *(undefined1 *)(puVar9 + 0x18) = 0;
  *(undefined1 *)((long)puVar9 + 0xc4) = 0;
  *(undefined1 *)(puVar9 + 0x19) = 0;
  *(undefined4 *)((long)puVar9 + 0xcc) = 0xffffffff;
  *(undefined1 *)(puVar9 + 0x1a) = 0;
  *(undefined1 *)((long)puVar9 + 0xd4) = 0;
  *(undefined1 *)(puVar9 + 0x1b) = 0;
  *(undefined1 *)((long)puVar9 + 0xdc) = 0;
  *(undefined1 *)(puVar9 + 0x1c) = 0;
  *(undefined1 *)((long)puVar9 + 0xe4) = 0;
  *(undefined1 *)(puVar9 + 0x1d) = 0;
  *(undefined1 *)((long)puVar9 + 0xec) = 0;
  *(undefined1 *)(puVar9 + 0x1e) = 0;
  puVar9[0x1f] = 0;
  lVar2 = *(long *)(param_1 + 0x90);
  if (lVar2 != 0) {
    *(undefined8 *)(param_1 + 0x90) = 0;
    *(long *)(this_00 + 0x90) = lVar2;
    *(string **)(lVar2 + 0x90) = this_00;
  }
  *(undefined8 **)(param_1 + 0x90) = puVar9;
  puVar9[0x12] = param_1;
  puVar9[0x11] = this_00;
  *(undefined8 **)(this_00 + 0x88) = puVar9;
  return;
}


// 001d6890  ATCFlightRoute::InsertCurrentLocation

/* ATCFlightRoute::InsertCurrentLocation(ATCAircraft*) */

ATCWaypoint * ATCFlightRoute::InsertCurrentLocation(ATCAircraft *param_1)

{
  ATCFlightSegment *pAVar1;
  ATCWaypoint *pAVar2;
  undefined8 *puVar3;
  ATCFlightRoute *in_RSI;
  undefined8 in_XMM1_Qa;
  ATCWaypoint *local_58;
  ATCWaypoint *local_50;
  undefined8 local_48;
  undefined8 local_40;
  undefined8 *local_38;
  undefined8 *local_30;
  undefined8 *local_28;
  
  if ((*(long *)param_1 == 0) ||
     (pAVar1 = *(ATCFlightSegment **)(*(long *)param_1 + 0x90), pAVar1 == (ATCFlightSegment *)0x0))
  {
    local_48 = (**(code **)(*(long *)in_RSI + 0x268))();
    local_40 = in_XMM1_Qa;
    puVar3 = operator_new(0x10);
    local_30 = puVar3 + 2;
    *puVar3 = local_48;
    puVar3[1] = local_40;
    local_38 = puVar3;
    local_28 = local_30;
    if (*(ATCWaypoint **)(param_1 + 8) == (ATCWaypoint *)0x0) {
      CreateChain((ATCFlightRoute *)param_1,(vector *)&local_38,&local_58,&local_50);
      *(ATCWaypoint **)param_1 = local_58;
      *(ATCWaypoint **)(param_1 + 8) = local_50;
      pAVar2 = local_50;
    }
    else {
      InsertAfter((ATCFlightRoute *)param_1,*(ATCWaypoint **)(param_1 + 8),(vector *)&local_38);
      pAVar2 = *(ATCWaypoint **)(param_1 + 8);
    }
    operator_delete(puVar3);
  }
  else {
    local_38 = (undefined8 *)(**(code **)(*(long *)in_RSI + 0x268))();
    pAVar2 = (ATCWaypoint *)Split(in_RSI,pAVar1,(GeoPoint2D *)&local_38);
  }
  return pAVar2;
}


// 001d6990  ATCFlightRoute::FindSegByTime

/* ATCFlightRoute::FindSegByTime(double, ATCFlightSegment const**) const */

undefined8 __thiscall
ATCFlightRoute::FindSegByTime(ATCFlightRoute *this,double param_1,ATCFlightSegment **param_2)

{
  long lVar1;
  ATCFlightSegment *pAVar2;
  
  if (*(long *)this != 0) {
    pAVar2 = *(ATCFlightSegment **)(*(long *)this + 0x90);
    while (pAVar2 != (ATCFlightSegment *)0x0) {
      lVar1 = *(long *)(pAVar2 + 0x88);
      if (param_1 < (double)*(float *)(*(long *)(pAVar2 + 0x90) + 0x38)) {
        if (lVar1 == 0) {
          return 0;
        }
      }
      else if (param_1 < (double)*(float *)(lVar1 + 0x38)) {
        *param_2 = pAVar2;
        return CONCAT71((int7)((ulong)pAVar2 >> 8),1);
      }
      pAVar2 = *(ATCFlightSegment **)(lVar1 + 0x90);
    }
  }
  return 0;
}


// 001d6a00  ATCFlightSegment::GetDstPt

/* ATCFlightSegment::GetDstPt() */

undefined8 __thiscall ATCFlightSegment::GetDstPt(ATCFlightSegment *this)

{
  return *(undefined8 *)(this + 0x88);
}


// 001d6a10  ATCFlightSegment::GetPrevSeg

/* ATCFlightSegment::GetPrevSeg() */

undefined8 __thiscall ATCFlightSegment::GetPrevSeg(ATCFlightSegment *this)

{
  if (*(long *)(this + 0x90) != 0) {
    return *(undefined8 *)(*(long *)(this + 0x90) + 0x88);
  }
  return 0;
}


// 001d6b00  ATCFlightRoute::FindGeoPtByTime

/* ATCFlightRoute::FindGeoPtByTime(double, GeoPoint2D&) */

undefined8 __thiscall
ATCFlightRoute::FindGeoPtByTime(ATCFlightRoute *this,double param_1,GeoPoint2D *param_2)

{
  long lVar1;
  long lVar2;
  UTL_geoid *pUVar3;
  GeoPoint2D *pGVar4;
  GeoPoint2D *pGVar5;
  float fVar6;
  float fVar7;
  float fVar8;
  undefined8 extraout_XMM0_Qa;
  ulong uVar9;
  
  if (*(long *)this != 0) {
    lVar1 = *(long *)(*(long *)this + 0x90);
    while (lVar1 != 0) {
      lVar2 = *(long *)(lVar1 + 0x88);
      fVar7 = *(float *)(*(long *)(lVar1 + 0x90) + 0x38);
      if ((double)fVar7 <= param_1) {
        fVar8 = *(float *)(lVar2 + 0x38);
        if (param_1 < (double)fVar8) {
          fVar6 = DAT_025246bc;
          if (fVar7 < fVar8) {
            fVar6 = (float)((param_1 - (double)fVar7) / (double)(fVar8 - fVar7));
          }
          pGVar5 = (GeoPoint2D *)(*(long *)(lVar1 + 0x90) + 0x40);
          pGVar4 = (GeoPoint2D *)(lVar2 + 0x40);
          pUVar3 = (UTL_geoid *)REN_geoid::instance();
          fVar7 = (float)ATCGeomDistBetweenLonLatPts(pUVar3,pGVar5,pGVar4);
          pUVar3 = (UTL_geoid *)REN_geoid::instance();
          fVar8 = (float)ATCGeomDistBetweenLonLatPts(pUVar3,pGVar5,pGVar4);
          fVar8 = (fVar7 * fVar6) / fVar8;
          uVar9 = (ulong)(uint)fVar8;
          ATCGeomPtOnGreatCircle(pUVar3,pGVar5,pGVar4,(double)fVar8);
          *(undefined8 *)param_2 = extraout_XMM0_Qa;
          *(ulong *)(param_2 + 8) = uVar9;
          return 1;
        }
      }
      else if (lVar2 == 0) {
        return 0;
      }
      lVar1 = *(long *)(lVar2 + 0x90);
    }
  }
  return 0;
}


// 001d6c20  ATCFlightRoute::FindGeoPtByDistFromEnd

/* ATCFlightRoute::FindGeoPtByDistFromEnd(units::value<float, units::scale<units::units::m, 1, 1852>
   >, GeoPoint2D&, ATCFlightSegment*&) */

undefined8 __thiscall
ATCFlightRoute::FindGeoPtByDistFromEnd
          (float param_1,ATCFlightRoute *this,undefined8 *param_3,long *param_4)

{
  long lVar1;
  undefined8 uVar2;
  UTL_geoid *pUVar3;
  long lVar4;
  long lVar5;
  float fVar6;
  undefined4 uVar7;
  undefined8 local_68;
  undefined8 uStack_60;
  undefined8 local_58;
  undefined8 uStack_50;
  undefined8 *local_40;
  float local_38;
  float local_34;
  
  *param_4 = 0;
  if ((*(long *)(this + 8) != 0) && (lVar5 = *(long *)(*(long *)(this + 8) + 0x88), lVar5 != 0)) {
    fVar6 = 0.0;
    local_40 = param_3;
    local_34 = param_1;
    do {
      lVar4 = *(long *)(lVar5 + 0x88);
      lVar1 = *(long *)(lVar5 + 0x90);
      local_38 = fVar6;
      pUVar3 = (UTL_geoid *)REN_geoid::instance();
      fVar6 = (float)ATCGeomDistBetweenLonLatPts
                               (pUVar3,(GeoPoint2D *)(lVar1 + 0x40),(GeoPoint2D *)(lVar4 + 0x40));
      fVar6 = fVar6 + local_38;
      if (local_34 < fVar6) {
        *param_4 = lVar5;
        local_68 = *(undefined8 *)(*(long *)(lVar5 + 0x90) + 0x40);
        uStack_60 = *(undefined8 *)(*(long *)(lVar5 + 0x90) + 0x48);
        local_58 = *(undefined8 *)(*(long *)(lVar5 + 0x88) + 0x40);
        uStack_50 = *(undefined8 *)(*(long *)(lVar5 + 0x88) + 0x48);
        lVar4 = *(long *)(*(long *)(this + 8) + 0x88);
        fVar6 = 0.0;
        if (lVar4 != lVar5) goto LAB_001d6d16;
        goto LAB_001d6d62;
      }
    } while ((*(long *)(lVar5 + 0x90) != 0) &&
            (lVar5 = *(long *)(*(long *)(lVar5 + 0x90) + 0x88), lVar5 != 0));
  }
  return 0;
LAB_001d6d16:
  lVar5 = *(long *)(lVar4 + 0x88);
  lVar1 = *(long *)(lVar4 + 0x90);
  local_38 = fVar6;
  pUVar3 = (UTL_geoid *)REN_geoid::instance();
  fVar6 = (float)ATCGeomDistBetweenLonLatPts
                           (pUVar3,(GeoPoint2D *)(lVar1 + 0x40),(GeoPoint2D *)(lVar5 + 0x40));
  if (*(long *)(lVar4 + 0x90) == 0) {
    lVar4 = 0;
    fVar6 = local_38 + fVar6;
    if (*param_4 == 0) goto LAB_001d6d62;
    goto LAB_001d6d16;
  }
  lVar4 = *(long *)(*(long *)(lVar4 + 0x90) + 0x88);
  fVar6 = local_38 + fVar6;
  if (lVar4 == *param_4) {
LAB_001d6d62:
    local_34 = local_34 - fVar6;
    pUVar3 = (UTL_geoid *)REN_geoid::instance();
    fVar6 = (float)ATCGeomDistBetweenLonLatPts
                             (pUVar3,(GeoPoint2D *)&local_58,(GeoPoint2D *)&local_68);
    uVar7 = 0;
    fVar6 = local_34 / fVar6;
    uVar2 = ATCGeomPtOnGreatCircle
                      (pUVar3,(GeoPoint2D *)&local_58,(GeoPoint2D *)&local_68,(double)fVar6);
    *local_40 = uVar2;
    local_40[1] = CONCAT44(uVar7,fVar6);
    return 1;
  }
  goto LAB_001d6d16;
}


// 001d6dc0  ATCFlightSegment::GetPrevSeg

/* ATCFlightSegment::GetPrevSeg() const */

undefined8 __thiscall ATCFlightSegment::GetPrevSeg(ATCFlightSegment *this)

{
  if (*(long *)(this + 0x90) != 0) {
    return *(undefined8 *)(*(long *)(this + 0x90) + 0x88);
  }
  return 0;
}


// 001d6de0  ATCFlightRoute::FindGeoPtByDist

/* ATCFlightRoute::FindGeoPtByDist(ATCAircraft*, units::value<float, units::scale<units::units::m,
   1, 1852> >, GeoPoint2D&) */

undefined8 __thiscall
ATCFlightRoute::FindGeoPtByDist
          (float param_1_00,ATCFlightRoute *this,ATCAircraft *param_1,undefined8 *param_4)

{
  double dVar1;
  long lVar2;
  long lVar3;
  undefined8 uVar4;
  UTL_geoid *pUVar5;
  ATCFlightSegment *pAVar6;
  ATCFlightSegment *pAVar7;
  GeoPoint2D *pGVar8;
  GeoPoint2D *pGVar9;
  float fVar10;
  ulong uVar11;
  double dVar12;
  undefined8 local_70;
  ulong local_68;
  undefined8 *local_60;
  undefined8 local_58;
  double dStack_50;
  undefined8 local_48;
  double dStack_40;
  float local_38;
  float local_34;
  
  if ((*(long *)this == 0) ||
     (pAVar6 = *(ATCFlightSegment **)(*(long *)this + 0x90), pAVar6 == (ATCFlightSegment *)0x0)) {
    return 0;
  }
  uVar11 = 0;
  local_38 = 0.0;
  pAVar7 = pAVar6;
  local_60 = param_4;
  local_34 = param_1_00;
  while( true ) {
    local_48 = (**(code **)(*(long *)param_1 + 0x268))(param_1);
    dStack_40 = (double)uVar11;
    fVar10 = (float)DistanceToRun(this,(GeoPoint2D *)&local_48,pAVar6,
                                  *(ATCWaypoint **)(pAVar6 + 0x88));
    uVar11 = (ulong)(uint)(local_38 + fVar10);
    if (local_34 < local_38 + fVar10) break;
    while( true ) {
      if (*(long *)(pAVar7 + 0x88) == 0) {
        return 0;
      }
      pAVar7 = *(ATCFlightSegment **)(*(long *)(pAVar7 + 0x88) + 0x90);
      if (pAVar7 == (ATCFlightSegment *)0x0) {
        return 0;
      }
      pAVar6 = *(ATCFlightSegment **)(*(long *)this + 0x90);
      local_38 = (float)uVar11;
      if (pAVar7 == pAVar6) break;
      lVar2 = *(long *)(pAVar7 + 0x88);
      lVar3 = *(long *)(pAVar7 + 0x90);
      pUVar5 = (UTL_geoid *)REN_geoid::instance();
      fVar10 = (float)ATCGeomDistBetweenLonLatPts
                                (pUVar5,(GeoPoint2D *)(lVar3 + 0x40),(GeoPoint2D *)(lVar2 + 0x40));
      uVar11 = (ulong)(uint)(local_38 + fVar10);
      if (local_34 < local_38 + fVar10) goto LAB_001d6ef0;
    }
  }
LAB_001d6ef0:
  if (pAVar7 != *(ATCFlightSegment **)(*(long *)this + 0x90)) {
    local_48 = *(undefined8 *)(*(long *)(pAVar7 + 0x90) + 0x40);
    dStack_40 = *(double *)(*(long *)(pAVar7 + 0x90) + 0x48);
    local_58 = *(undefined8 *)(*(long *)(pAVar7 + 0x88) + 0x40);
    dStack_50 = *(double *)(*(long *)(pAVar7 + 0x88) + 0x48);
    local_70 = (**(code **)(*(long *)param_1 + 0x268))(param_1);
    local_68 = uVar11;
    pAVar6 = (ATCFlightSegment *)ATCAircraft::GetCurrentSegment(param_1);
    fVar10 = (float)DistanceToRun(this,(GeoPoint2D *)&local_70,pAVar6,
                                  *(ATCWaypoint **)(pAVar7 + 0x90));
    local_34 = local_34 - fVar10;
    pUVar5 = (UTL_geoid *)REN_geoid::instance();
    pGVar8 = (GeoPoint2D *)&local_48;
    pGVar9 = (GeoPoint2D *)&local_58;
    goto LAB_001d7041;
  }
  local_58 = 0;
  dStack_50 = 0.0;
  lVar2 = *(long *)(pAVar7 + 0x88);
  lVar3 = *(long *)(pAVar7 + 0x90);
  pUVar5 = (UTL_geoid *)REN_geoid::instance();
  dVar12 = *(double *)(lVar3 + 0x40);
  dVar1 = *(double *)(lVar2 + 0x40);
  if ((dVar12 != dVar1) || (NAN(dVar12) || NAN(dVar1))) {
LAB_001d6fb3:
    if (dVar12 == DAT_0253ae78) {
      if ((dVar1 == DAT_0253ae78) && (!NAN(dVar1) && !NAN(DAT_0253ae78))) goto LAB_001d700b;
    }
    if (dVar12 == DAT_0253ae80) {
      if ((dVar1 == DAT_0253ae80) && (!NAN(dVar1) && !NAN(DAT_0253ae80))) goto LAB_001d700b;
    }
    fVar10 = (float)ATCGeomDistBetweenLonLatPts
                              (pUVar5,(GeoPoint2D *)(lVar3 + 0x40),(GeoPoint2D *)(lVar2 + 0x40));
    dVar12 = DAT_0253ae88;
    if ((double)fVar10 < DAT_0253ae88) goto LAB_001d700b;
    lVar2 = *(long *)(pAVar7 + 0x88);
    lVar3 = *(long *)(pAVar7 + 0x90);
    local_48 = (**(code **)(*(long *)param_1 + 0x268))(param_1);
    dStack_40 = dVar12;
    pUVar5 = (UTL_geoid *)REN_geoid::instance();
    local_58 = ATCGeomProjectPointRoundWorld
                         (pUVar5,(GeoPoint2D *)(lVar3 + 0x40),(GeoPoint2D *)(lVar2 + 0x40),
                          (GeoPoint2D *)&local_48);
  }
  else {
    if ((*(double *)(lVar3 + 0x48) != *(double *)(lVar2 + 0x48)) ||
       (NAN(*(double *)(lVar3 + 0x48)) || NAN(*(double *)(lVar2 + 0x48)))) goto LAB_001d6fb3;
LAB_001d700b:
    local_58 = (**(code **)(*(long *)param_1 + 0x268))(param_1);
  }
  local_48 = *(undefined8 *)(*(long *)(pAVar7 + 0x88) + 0x40);
  dStack_40 = *(double *)(*(long *)(pAVar7 + 0x88) + 0x48);
  dStack_50 = dVar12;
  pUVar5 = (UTL_geoid *)REN_geoid::instance();
  pGVar8 = (GeoPoint2D *)&local_58;
  pGVar9 = (GeoPoint2D *)&local_48;
LAB_001d7041:
  fVar10 = (float)ATCGeomDistBetweenLonLatPts(pUVar5,pGVar8,pGVar9);
  uVar11 = (ulong)(uint)(local_34 / fVar10);
  uVar4 = ATCGeomPtOnGreatCircle(pUVar5,pGVar8,pGVar9,(double)(local_34 / fVar10));
  *local_60 = uVar4;
  local_60[1] = uVar11;
  return 1;
}


// 001d70d0  ATCFlightRoute::ResetInitialETA

/* ATCFlightRoute::ResetInitialETA() */

void __thiscall ATCFlightRoute::ResetInitialETA(ATCFlightRoute *this)

{
  if (*(long *)this != 0) {
    *(float *)(*(long *)this + 0x38) = (float)DAT_0315d538;
  }
  return;
}


// 001d7100  ATCFlightRoute::ResetInitialAltEst

/* ATCFlightRoute::ResetInitialAltEst(units::value<float, units::units::m>) */

void __thiscall ATCFlightRoute::ResetInitialAltEst(float param_1,ATCFlightRoute *this)

{
  *(float *)(*(long *)this + 0x3c) =
       ((param_1 * DAT_02525330 * DAT_02525330) / DAT_02536f14) / DAT_02536f10;
  return;
}


// 001d73c0  ATCFlightRoute::PrintRoutingWithFunc

/* WARNING: Type propagation algorithm not settling */
/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* ATCFlightRoute::PrintRoutingWithFunc(int (*)(void*, char const*, ...), void*, bool) const */

void __thiscall
ATCFlightRoute::PrintRoutingWithFunc
          (ATCFlightRoute *this,_func_int_void_ptr_char_ptr____ *param_1,void *param_2,bool param_3)

{
  GeoPoint2D *pGVar1;
  double *pdVar2;
  double dVar3;
  uint uVar4;
  uint *puVar5;
  long *plVar6;
  long *plVar7;
  undefined1 uVar8;
  int iVar9;
  undefined8 uVar10;
  UTL_geoid *pUVar11;
  __tree_node_base *p_Var12;
  long *plVar13;
  undefined1 extraout_DL;
  undefined1 extraout_DL_00;
  undefined1 extraout_DL_01;
  undefined1 extraout_DL_02;
  undefined1 extraout_DL_03;
  char cVar14;
  undefined1 extraout_DL_04;
  undefined1 extraout_DL_05;
  undefined1 extraout_DL_06;
  ulong extraout_RDX;
  ulong uVar15;
  char *pcVar16;
  long lVar17;
  long lVar18;
  GeoPoint2D *extraout_RDX_00;
  GeoPoint2D *pGVar19;
  byte *pbVar20;
  byte *pbVar21;
  ulong extraout_RDX_01;
  ulong extraout_RDX_02;
  long lVar22;
  __tree_node_base **pp_Var23;
  __tree_node_base **pp_Var24;
  byte *pbVar25;
  bool bVar26;
  float fVar27;
  undefined4 uVar28;
  double dVar29;
  undefined4 uVar30;
  double dVar31;
  byte local_f0;
  undefined4 local_ef;
  undefined1 local_eb;
  undefined1 local_ea;
  void *local_e0;
  byte local_d8;
  undefined4 local_d7;
  undefined1 local_d3;
  undefined1 local_d2;
  void *local_c8;
  byte local_c0;
  undefined4 local_bf;
  undefined1 local_bb;
  undefined1 local_ba;
  void *local_b0;
  int local_a4;
  double local_a0;
  double local_98;
  int *local_90;
  __tree_node_base *local_88;
  double local_70;
  undefined8 local_68;
  undefined8 uStack_60;
  char *local_58;
  undefined4 local_48;
  undefined1 uStack_44;
  undefined1 uStack_43;
  undefined1 uStack_42;
  undefined1 uStack_41;
  undefined4 uStack_40;
  undefined4 uStack_3c;
  char *local_38;
  
  local_68 = 0;
  uStack_60 = 0;
  local_58 = (char *)0x0;
  (*param_1)(param_2,"==================================================\n",(char)param_2);
  (*param_1)(param_2,"Routing is currently: ",extraout_DL);
  if (param_3) {
    uVar8 = 0x90;
    if (this[0x18] == (ATCFlightRoute)0x0) {
      uVar8 = 0x92;
    }
    (*param_1)(param_2,"  Raw view: can_edit=%s edit_count=%d\n",uVar8);
    uVar15 = extraout_RDX;
    if (*(long *)this != 0) {
      uVar15 = 0;
      lVar17 = *(long *)this;
LAB_001d7462:
      puVar5 = *(uint **)(lVar17 + 0x90);
      if (puVar5 == (uint *)0x0) {
        lVar22 = 0;
      }
      else {
        lVar22 = *(long *)(puVar5 + 0x22);
      }
      local_a4 = (int)uVar15;
      stl_printf((char *)&local_48,(int)*(undefined8 *)(lVar17 + 0x48),
                 (int)*(undefined8 *)(lVar17 + 0x40),"  Wpt %d: (\'%s\') lon=%lf, lat=%lf");
      if ((local_68 & 1) != 0) {
        operator_delete(local_58);
      }
      local_58 = local_38;
      local_68 = CONCAT17(uStack_41,
                          CONCAT16(uStack_42,CONCAT15(uStack_43,CONCAT14(uStack_44,local_48))));
      uStack_60 = CONCAT44(uStack_3c,uStack_40);
      if (*(long *)(lVar17 + 0x18) != 0) {
        uVar10 = apt_get_string(*(uint *)(*(long *)(lVar17 + 0x18) + 0x1c));
        stl_printf((char *)&local_48,", gate = %s (%d)",uVar10);
        pcVar16 = local_38;
        if ((local_48 & 1) == 0) {
          pcVar16 = (char *)((long)&local_48 + 1);
        }
        std::string::append((char *)&local_68,(ulong)pcVar16);
        if ((local_48 & 1) != 0) {
          operator_delete(local_38);
        }
      }
      if (*(int *)(lVar17 + 0x98) != 0) {
        pcVar16 = "APT";
        switch(*(int *)(lVar17 + 0x98)) {
        case 1:
          break;
        case 2:
          pcVar16 = "NDB";
          break;
        case 3:
          pcVar16 = "VOR";
          break;
        default:
          pcVar16 = "???";
          break;
        case 0xb:
          pcVar16 = "FIX";
        }
        stl_printf((char *)&local_48,", Nav type = %s",pcVar16);
        pcVar16 = local_38;
        if ((local_48 & 1) == 0) {
          pcVar16 = (char *)((long)&local_48 + 1);
        }
        std::string::append((char *)&local_68,(ulong)pcVar16);
        if ((local_48 & 1) != 0) {
          operator_delete(local_38);
        }
      }
      std::operator+((string *)&local_48,(char *)&local_68);
      pcVar16 = (char *)((long)&local_48 + 1);
      if ((local_48 & 1) != 0) {
        pcVar16 = local_38;
      }
      (*param_1)(param_2,pcVar16,extraout_DL_00);
      if ((local_48 & 1) != 0) {
        operator_delete(local_38);
      }
      if (puVar5 != (uint *)0x0) {
        if ((puVar5[0xc] & 1) == 0) {
          lVar17 = (long)puVar5 + 0x31;
        }
        else {
          lVar17 = *(long *)(puVar5 + 0x10);
        }
        stl_printf((char *)&local_48,"    Seg \'%s\': ",lVar17);
        if ((local_68 & 1) != 0) {
          operator_delete(local_58);
        }
        local_58 = local_38;
        local_68 = CONCAT44(CONCAT13(uStack_41,CONCAT12(uStack_42,CONCAT11(uStack_43,uStack_44))),
                            local_48);
        uStack_60 = CONCAT44(uStack_3c,uStack_40);
        if (((char)PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kGroundHoldNames
             == '\0') &&
           (iVar9 = ___cxa_guard_acquire
                              (&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                                kGroundHoldNames), iVar9 != 0)) {
          _DAT_02dbb068 = 0;
          PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kGroundHoldNames =
               &DAT_02dbb060;
          local_88 = (__tree_node_base *)0x0;
          local_70 = 0.0;
          do {
            local_90 = (int *)(&DAT_02ad0c08 + (long)local_70 * 0x10);
            pp_Var24 = &DAT_02dbb060;
            if ((__tree_node_base **)
                PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kGroundHoldNames ==
                &DAT_02dbb060) {
LAB_001d85ee:
              if (local_88 == (__tree_node_base *)0x0) {
LAB_001d8643:
                pp_Var23 = &DAT_02dbb060;
                pp_Var24 = &DAT_02dbb060;
                goto LAB_001d864d;
              }
              pp_Var23 = (__tree_node_base **)((long)pp_Var24 + 8);
              lVar17 = (long)*pp_Var23;
            }
            else {
              p_Var12 = local_88;
              if (local_88 == (__tree_node_base *)0x0) {
                pp_Var24 = (__tree_node_base **)
                           CONCAT71(PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                                    kGroundHoldNames._1_7_,
                                    (char)PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)
                                          ::kGroundHoldNames);
                p_Var12 = (__tree_node_base *)pp_Var24;
                if (*pp_Var24 == (__tree_node_base *)&DAT_02dbb060) {
                  do {
                    pp_Var24 = *(__tree_node_base ***)(p_Var12 + 0x10);
                    bVar26 = *pp_Var24 == p_Var12;
                    p_Var12 = (__tree_node_base *)pp_Var24;
                  } while (bVar26);
                }
              }
              else {
                do {
                  pp_Var24 = (__tree_node_base **)p_Var12;
                  p_Var12 = *(__tree_node_base **)((long)pp_Var24 + 8);
                } while (*(__tree_node_base **)((long)pp_Var24 + 8) != (__tree_node_base *)0x0);
              }
              iVar9 = *local_90;
              if (*(int *)((long)pp_Var24 + 0x20) < iVar9) goto LAB_001d85ee;
              if (local_88 == (__tree_node_base *)0x0) goto LAB_001d8643;
              pp_Var23 = &DAT_02dbb060;
              p_Var12 = local_88;
              do {
                while (pp_Var24 = (__tree_node_base **)p_Var12,
                      iVar9 < *(int *)((long)pp_Var24 + 0x20)) {
                  pp_Var23 = pp_Var24;
                  p_Var12 = *pp_Var24;
                  if (*pp_Var24 == (__tree_node_base *)0x0) {
                    lVar17 = (long)*pp_Var24;
                    goto joined_r0x001d8709;
                  }
                }
                if (iVar9 <= *(int *)((long)pp_Var24 + 0x20)) break;
                pp_Var23 = (__tree_node_base **)((long)pp_Var24 + 8);
                p_Var12 = *(__tree_node_base **)((long)pp_Var24 + 8);
              } while (*(__tree_node_base **)((long)pp_Var24 + 8) != (__tree_node_base *)0x0);
LAB_001d864d:
              lVar17 = (long)*pp_Var23;
            }
joined_r0x001d8709:
            DAT_02dbb060 = local_88;
            if (lVar17 == 0) {
              p_Var12 = operator_new(0x30);
              uVar10 = *(undefined8 *)(local_90 + 2);
              *(undefined8 *)(p_Var12 + 0x20) = *(undefined8 *)local_90;
              *(undefined8 *)(p_Var12 + 0x28) = uVar10;
              *(undefined8 *)p_Var12 = 0;
              *(undefined8 *)(p_Var12 + 8) = 0;
              *(__tree_node_base ***)(p_Var12 + 0x10) = pp_Var24;
              *pp_Var23 = p_Var12;
              if ((undefined8 *)
                  *PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kGroundHoldNames
                  != (undefined8 *)0x0) {
                p_Var12 = *pp_Var23;
                PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kGroundHoldNames =
                     (undefined8 *)
                     *PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                      kGroundHoldNames;
              }
              std::__tree_balance_after_insert<std::__tree_node_base<void*>*>(DAT_02dbb060,p_Var12);
              _DAT_02dbb068 = _DAT_02dbb068 + 1;
            }
            local_70 = (double)((long)local_70 + 1);
            if (local_70 == 3.45845952088873e-323) goto LAB_001d8c14;
            local_88 = DAT_02dbb060;
          } while( true );
        }
        goto LAB_001d769a;
      }
      goto LAB_001d7450;
    }
  }
  else {
    pbVar20 = *(byte **)this;
    if (pbVar20 != (byte *)0x0) {
      do {
        lVar17 = *(long *)(pbVar20 + 0x90);
        if (lVar17 == 0) {
          pbVar25 = (byte *)0x0;
          if ((*pbVar20 & 1) == 0) goto LAB_001d8d04;
LAB_001d8d18:
          pbVar21 = *(byte **)(pbVar20 + 0x10);
          pbVar20 = pbVar25;
        }
        else {
          pbVar25 = *(byte **)(lVar17 + 0x88);
          if ((*pbVar20 & 1) != 0) goto LAB_001d8d18;
LAB_001d8d04:
          pbVar21 = pbVar20 + 1;
          pbVar20 = pbVar25;
        }
        stl_printf((char *)&local_48,"|%s|",pbVar21);
        if ((local_68 & 1) != 0) {
          operator_delete(local_58);
        }
        local_58 = local_38;
        local_68 = CONCAT44(CONCAT13(uStack_41,CONCAT12(uStack_42,CONCAT11(uStack_43,uStack_44))),
                            local_48);
        uStack_60 = CONCAT44(uStack_3c,uStack_40);
        if (lVar17 != 0) {
          if ((*(byte *)(lVar17 + 0x30) & 1) == 0) {
            pcVar16 = "???";
            if (1 < *(byte *)(lVar17 + 0x30)) {
              pcVar16 = (char *)(lVar17 + 0x31);
            }
          }
          else {
            pcVar16 = "???";
            if (*(long *)(lVar17 + 0x38) != 0) {
              pcVar16 = *(char **)(lVar17 + 0x40);
            }
          }
          stl_printf((char *)&local_48,"--- %s ---",pcVar16);
          pcVar16 = local_38;
          if ((local_48 & 1) == 0) {
            pcVar16 = (char *)((long)&local_48 + 1);
          }
          std::string::append((char *)&local_68,(ulong)pcVar16);
          if ((local_48 & 1) != 0) {
            operator_delete(local_38);
          }
        }
      } while (pbVar20 != (byte *)0x0);
    }
    std::operator+((string *)&local_48,(char *)&local_68);
    pcVar16 = local_38;
    if ((local_48 & 1) == 0) {
      pcVar16 = (char *)((long)&local_48 + 1);
    }
    (*param_1)(param_2,pcVar16,extraout_DL_06);
    uVar15 = extraout_RDX_01;
    if ((local_48 & 1) != 0) {
      operator_delete(local_38);
      uVar15 = extraout_RDX_02;
    }
  }
LAB_001d8e23:
  (*param_1)(param_2,"==================================================\n",(char)uVar15);
  if ((local_68 & 1) != 0) {
    operator_delete(local_58);
  }
  return;
LAB_001d8c14:
  ___cxa_atexit(std::
                map<ATCGndHoldSubtype,char_const*,std::less<ATCGndHoldSubtype>,std::allocator<std::pair<ATCGndHoldSubtype_const,char_const*>>>
                ::~map,&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                        kGroundHoldNames,0x10000);
  ___cxa_guard_release
            (&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kGroundHoldNames);
LAB_001d769a:
  if ((PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kIFRNavNames == '\0') &&
     (iVar9 = ___cxa_guard_acquire
                        (&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                          kIFRNavNames), iVar9 != 0)) {
    DAT_02dbb088 = 0;
    PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kIFRNavNames = &DAT_02dbb080;
    local_88 = (__tree_node_base *)0x0;
    local_70 = 0.0;
    do {
      local_90 = (int *)(&DAT_02ad0c78 + (long)local_70 * 0x10);
      pp_Var24 = &DAT_02dbb080;
      if ((__tree_node_base **)
          PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kIFRNavNames ==
          &DAT_02dbb080) {
LAB_001d879a:
        if (local_88 == (__tree_node_base *)0x0) {
LAB_001d87ef:
          pp_Var23 = &DAT_02dbb080;
          pp_Var24 = &DAT_02dbb080;
          goto LAB_001d87f9;
        }
        pp_Var23 = (__tree_node_base **)((long)pp_Var24 + 8);
        lVar17 = (long)*pp_Var23;
      }
      else {
        p_Var12 = local_88;
        if (local_88 == (__tree_node_base *)0x0) {
          pp_Var24 = (__tree_node_base **)
                     CONCAT71(uRam0000000002dbb091,
                              PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                              kIFRNavNames);
          p_Var12 = (__tree_node_base *)pp_Var24;
          if (*pp_Var24 == (__tree_node_base *)&DAT_02dbb080) {
            do {
              pp_Var24 = *(__tree_node_base ***)(p_Var12 + 0x10);
              bVar26 = *pp_Var24 == p_Var12;
              p_Var12 = (__tree_node_base *)pp_Var24;
            } while (bVar26);
          }
        }
        else {
          do {
            pp_Var24 = (__tree_node_base **)p_Var12;
            p_Var12 = *(__tree_node_base **)((long)pp_Var24 + 8);
          } while (*(__tree_node_base **)((long)pp_Var24 + 8) != (__tree_node_base *)0x0);
        }
        iVar9 = *local_90;
        if (*(int *)((long)pp_Var24 + 0x20) < iVar9) goto LAB_001d879a;
        if (local_88 == (__tree_node_base *)0x0) goto LAB_001d87ef;
        pp_Var23 = &DAT_02dbb080;
        p_Var12 = local_88;
        do {
          while (pp_Var24 = (__tree_node_base **)p_Var12, iVar9 < *(int *)((long)pp_Var24 + 0x20)) {
            pp_Var23 = pp_Var24;
            p_Var12 = *pp_Var24;
            if (*pp_Var24 == (__tree_node_base *)0x0) {
              lVar17 = (long)*pp_Var24;
              goto joined_r0x001d88b5;
            }
          }
          if (iVar9 <= *(int *)((long)pp_Var24 + 0x20)) break;
          pp_Var23 = (__tree_node_base **)((long)pp_Var24 + 8);
          p_Var12 = *(__tree_node_base **)((long)pp_Var24 + 8);
        } while (*(__tree_node_base **)((long)pp_Var24 + 8) != (__tree_node_base *)0x0);
LAB_001d87f9:
        lVar17 = (long)*pp_Var23;
      }
joined_r0x001d88b5:
      DAT_02dbb080 = local_88;
      if (lVar17 == 0) {
        p_Var12 = operator_new(0x30);
        uVar10 = *(undefined8 *)(local_90 + 2);
        *(undefined8 *)(p_Var12 + 0x20) = *(undefined8 *)local_90;
        *(undefined8 *)(p_Var12 + 0x28) = uVar10;
        *(undefined8 *)p_Var12 = 0;
        *(undefined8 *)(p_Var12 + 8) = 0;
        *(__tree_node_base ***)(p_Var12 + 0x10) = pp_Var24;
        *pp_Var23 = p_Var12;
        if ((undefined8 *)
            *PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kIFRNavNames !=
            (undefined8 *)0x0) {
          p_Var12 = *pp_Var23;
          PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kIFRNavNames =
               (undefined8 *)
               *PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kIFRNavNames;
        }
        std::__tree_balance_after_insert<std::__tree_node_base<void*>*>(DAT_02dbb080,p_Var12);
        DAT_02dbb088 = DAT_02dbb088 + 1;
      }
      local_70 = (double)((long)local_70 + 1);
      if (local_70 == 1.97626258336499e-323) goto LAB_001d8c3f;
      local_88 = DAT_02dbb080;
    } while( true );
  }
LAB_001d76a8:
  if ((PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kVectorNavNames == '\0') &&
     (iVar9 = ___cxa_guard_acquire
                        (&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                          kVectorNavNames), iVar9 != 0)) {
    DAT_02dbb0a8 = 0;
    PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kVectorNavNames = &DAT_02dbb0a0;
    local_88 = (__tree_node_base *)0x0;
    local_70 = 0.0;
    do {
      local_90 = (int *)(&DAT_02ad0cb8 + (long)local_70 * 0x10);
      pp_Var24 = &DAT_02dbb0a0;
      if ((__tree_node_base **)
          PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kVectorNavNames ==
          &DAT_02dbb0a0) {
LAB_001d8946:
        if (local_88 == (__tree_node_base *)0x0) {
LAB_001d899b:
          pp_Var23 = &DAT_02dbb0a0;
          pp_Var24 = &DAT_02dbb0a0;
          goto LAB_001d89a5;
        }
        pp_Var23 = (__tree_node_base **)((long)pp_Var24 + 8);
        lVar17 = (long)*pp_Var23;
      }
      else {
        p_Var12 = local_88;
        if (local_88 == (__tree_node_base *)0x0) {
          pp_Var24 = (__tree_node_base **)
                     CONCAT71(uRam0000000002dbb0b1,
                              PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                              kVectorNavNames);
          p_Var12 = (__tree_node_base *)pp_Var24;
          if (*pp_Var24 == (__tree_node_base *)&DAT_02dbb0a0) {
            do {
              pp_Var24 = *(__tree_node_base ***)(p_Var12 + 0x10);
              bVar26 = *pp_Var24 == p_Var12;
              p_Var12 = (__tree_node_base *)pp_Var24;
            } while (bVar26);
          }
        }
        else {
          do {
            pp_Var24 = (__tree_node_base **)p_Var12;
            p_Var12 = *(__tree_node_base **)((long)pp_Var24 + 8);
          } while (*(__tree_node_base **)((long)pp_Var24 + 8) != (__tree_node_base *)0x0);
        }
        iVar9 = *local_90;
        if (*(int *)((long)pp_Var24 + 0x20) < iVar9) goto LAB_001d8946;
        if (local_88 == (__tree_node_base *)0x0) goto LAB_001d899b;
        pp_Var23 = &DAT_02dbb0a0;
        p_Var12 = local_88;
        do {
          while (pp_Var24 = (__tree_node_base **)p_Var12, iVar9 < *(int *)((long)pp_Var24 + 0x20)) {
            pp_Var23 = pp_Var24;
            p_Var12 = *pp_Var24;
            if (*pp_Var24 == (__tree_node_base *)0x0) {
              lVar17 = (long)*pp_Var24;
              goto joined_r0x001d8a61;
            }
          }
          if (iVar9 <= *(int *)((long)pp_Var24 + 0x20)) break;
          pp_Var23 = (__tree_node_base **)((long)pp_Var24 + 8);
          p_Var12 = *(__tree_node_base **)((long)pp_Var24 + 8);
        } while (*(__tree_node_base **)((long)pp_Var24 + 8) != (__tree_node_base *)0x0);
LAB_001d89a5:
        lVar17 = (long)*pp_Var23;
      }
joined_r0x001d8a61:
      DAT_02dbb0a0 = local_88;
      if (lVar17 == 0) {
        p_Var12 = operator_new(0x30);
        uVar10 = *(undefined8 *)(local_90 + 2);
        *(undefined8 *)(p_Var12 + 0x20) = *(undefined8 *)local_90;
        *(undefined8 *)(p_Var12 + 0x28) = uVar10;
        *(undefined8 *)p_Var12 = 0;
        *(undefined8 *)(p_Var12 + 8) = 0;
        *(__tree_node_base ***)(p_Var12 + 0x10) = pp_Var24;
        *pp_Var23 = p_Var12;
        if ((undefined8 *)
            *PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kVectorNavNames !=
            (undefined8 *)0x0) {
          p_Var12 = *pp_Var23;
          PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kVectorNavNames =
               (undefined8 *)
               *PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kVectorNavNames;
        }
        std::__tree_balance_after_insert<std::__tree_node_base<void*>*>(DAT_02dbb0a0,p_Var12);
        DAT_02dbb0a8 = DAT_02dbb0a8 + 1;
      }
      local_70 = (double)((long)local_70 + 1);
      if (local_70 == 2.47032822920623e-323) goto LAB_001d8c6a;
      local_88 = DAT_02dbb0a0;
    } while( true );
  }
LAB_001d76b6:
  if ((PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kRunwayNavNames == '\0') &&
     (iVar9 = ___cxa_guard_acquire
                        (&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                          kRunwayNavNames), iVar9 != 0)) {
    DAT_02dbb0c8 = 0;
    PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kRunwayNavNames = &DAT_02dbb0c0;
    local_88 = (__tree_node_base *)0x0;
    local_70 = 0.0;
    do {
      local_90 = (int *)(&DAT_02ad0d08 + (long)local_70 * 0x10);
      pp_Var24 = &DAT_02dbb0c0;
      if ((__tree_node_base **)
          PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kRunwayNavNames ==
          &DAT_02dbb0c0) {
LAB_001d8af2:
        if (local_88 == (__tree_node_base *)0x0) {
LAB_001d8b47:
          pp_Var23 = &DAT_02dbb0c0;
          pp_Var24 = &DAT_02dbb0c0;
          goto LAB_001d8b51;
        }
        pp_Var23 = (__tree_node_base **)((long)pp_Var24 + 8);
        lVar17 = (long)*pp_Var23;
      }
      else {
        p_Var12 = local_88;
        if (local_88 == (__tree_node_base *)0x0) {
          pp_Var24 = (__tree_node_base **)
                     CONCAT71(uRam0000000002dbb0d1,
                              PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                              kRunwayNavNames);
          p_Var12 = (__tree_node_base *)pp_Var24;
          if (*pp_Var24 == (__tree_node_base *)&DAT_02dbb0c0) {
            do {
              pp_Var24 = *(__tree_node_base ***)(p_Var12 + 0x10);
              bVar26 = *pp_Var24 == p_Var12;
              p_Var12 = (__tree_node_base *)pp_Var24;
            } while (bVar26);
          }
        }
        else {
          do {
            pp_Var24 = (__tree_node_base **)p_Var12;
            p_Var12 = *(__tree_node_base **)((long)pp_Var24 + 8);
          } while (*(__tree_node_base **)((long)pp_Var24 + 8) != (__tree_node_base *)0x0);
        }
        iVar9 = *local_90;
        if (*(int *)((long)pp_Var24 + 0x20) < iVar9) goto LAB_001d8af2;
        if (local_88 == (__tree_node_base *)0x0) goto LAB_001d8b47;
        pp_Var23 = &DAT_02dbb0c0;
        p_Var12 = local_88;
        do {
          while (pp_Var24 = (__tree_node_base **)p_Var12, iVar9 < *(int *)((long)pp_Var24 + 0x20)) {
            pp_Var23 = pp_Var24;
            p_Var12 = *pp_Var24;
            if (*pp_Var24 == (__tree_node_base *)0x0) {
              lVar17 = (long)*pp_Var24;
              goto joined_r0x001d8c0d;
            }
          }
          if (iVar9 <= *(int *)((long)pp_Var24 + 0x20)) break;
          pp_Var23 = (__tree_node_base **)((long)pp_Var24 + 8);
          p_Var12 = *(__tree_node_base **)((long)pp_Var24 + 8);
        } while (*(__tree_node_base **)((long)pp_Var24 + 8) != (__tree_node_base *)0x0);
LAB_001d8b51:
        lVar17 = (long)*pp_Var23;
      }
joined_r0x001d8c0d:
      DAT_02dbb0c0 = local_88;
      if (lVar17 == 0) {
        p_Var12 = operator_new(0x30);
        uVar10 = *(undefined8 *)(local_90 + 2);
        *(undefined8 *)(p_Var12 + 0x20) = *(undefined8 *)local_90;
        *(undefined8 *)(p_Var12 + 0x28) = uVar10;
        *(undefined8 *)p_Var12 = 0;
        *(undefined8 *)(p_Var12 + 8) = 0;
        *(__tree_node_base ***)(p_Var12 + 0x10) = pp_Var24;
        *pp_Var23 = p_Var12;
        if ((undefined8 *)
            *PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kRunwayNavNames !=
            (undefined8 *)0x0) {
          p_Var12 = *pp_Var23;
          PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kRunwayNavNames =
               (undefined8 *)
               *PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kRunwayNavNames;
        }
        std::__tree_balance_after_insert<std::__tree_node_base<void*>*>(DAT_02dbb0c0,p_Var12);
        DAT_02dbb0c8 = DAT_02dbb0c8 + 1;
      }
      local_70 = (double)((long)local_70 + 1);
      if (local_70 == 4.44659081257122e-323) goto LAB_001d8c95;
      local_88 = DAT_02dbb0c0;
    } while( true );
  }
LAB_001d76c4:
  switch(*puVar5) {
  case 1:
    if (DAT_02dbb060 != (__tree_node_base *)0x0) {
      uVar4 = puVar5[4];
      pp_Var24 = &DAT_02dbb060;
      p_Var12 = DAT_02dbb060;
      do {
        if ((int)uVar4 <= *(int *)(p_Var12 + 0x20)) {
          pp_Var24 = (__tree_node_base **)p_Var12;
        }
        p_Var12 = *(__tree_node_base **)
                   (p_Var12 + (ulong)(*(int *)(p_Var12 + 0x20) < (int)uVar4) * 8);
      } while (p_Var12 != (__tree_node_base *)0x0);
      if ((pp_Var24 != &DAT_02dbb060) && (*(int *)((long)pp_Var24 + 0x20) <= (int)uVar4)) {
        std::string::append((char *)&local_68);
        break;
      }
    }
    std::string::append((char *)&local_68);
    break;
  case 2:
    std::string::append((char *)&local_68);
    break;
  case 3:
    if (DAT_02dbb080 == (__tree_node_base *)0x0) {
LAB_001d77bb:
      std::string::append((char *)&local_68);
    }
    else {
      uVar4 = puVar5[3];
      pp_Var24 = &DAT_02dbb080;
      p_Var12 = DAT_02dbb080;
      do {
        if ((int)uVar4 <= *(int *)(p_Var12 + 0x20)) {
          pp_Var24 = (__tree_node_base **)p_Var12;
        }
        p_Var12 = *(__tree_node_base **)
                   (p_Var12 + (ulong)(*(int *)(p_Var12 + 0x20) < (int)uVar4) * 8);
      } while (p_Var12 != (__tree_node_base *)0x0);
      if ((pp_Var24 == &DAT_02dbb080) || ((int)uVar4 < *(int *)((long)pp_Var24 + 0x20)))
      goto LAB_001d77bb;
      std::string::append((char *)&local_68);
    }
    if (puVar5[3] == 2) {
      lVar17 = *(long *)(puVar5 + 0x1e);
      if (lVar17 == 0) {
        std::string::append((char *)&local_68);
      }
      else {
        stl_printf((char *)&local_48," @ %s/%s",*(undefined8 *)(lVar17 + 0x60),lVar17 + 0x54);
        pcVar16 = local_38;
        if ((local_48 & 1) == 0) {
          pcVar16 = (char *)((long)&local_48 + 1);
        }
        std::string::append((char *)&local_68,(ulong)pcVar16);
        if ((local_48 & 1) != 0) {
          operator_delete(local_38);
        }
      }
      pcVar16 = "Runway is null!";
      if (*(long *)(puVar5 + 0x28) != 0) {
        pcVar16 = (char *)runway_spec_t::to_string((runway_spec_t *)(puVar5 + 0x28));
      }
      stl_printf((char *)&local_48," rwy %s",pcVar16);
      pcVar16 = local_38;
      if ((local_48 & 1) == 0) {
        pcVar16 = (char *)((long)&local_48 + 1);
      }
      std::string::append((char *)&local_68,(ulong)pcVar16);
      goto LAB_001d7c30;
    }
    break;
  case 4:
    std::string::append((char *)&local_68);
    break;
  case 5:
    stl_printf((char *)&local_48,"veczone = %d ",(ulong)puVar5[0x20]);
    pcVar16 = local_38;
    if ((local_48 & 1) == 0) {
      pcVar16 = (char *)((long)&local_48 + 1);
    }
    std::string::append((char *)&local_68,(ulong)pcVar16);
    if ((local_48 & 1) != 0) {
      operator_delete(local_38);
    }
    if (DAT_02dbb0a0 == (__tree_node_base *)0x0) {
LAB_001d79bb:
      std::string::append((char *)&local_68);
    }
    else {
      uVar4 = puVar5[1];
      pp_Var24 = &DAT_02dbb0a0;
      p_Var12 = DAT_02dbb0a0;
      do {
        if ((int)uVar4 <= *(int *)(p_Var12 + 0x20)) {
          pp_Var24 = (__tree_node_base **)p_Var12;
        }
        p_Var12 = *(__tree_node_base **)
                   (p_Var12 + (ulong)(*(int *)(p_Var12 + 0x20) < (int)uVar4) * 8);
      } while (p_Var12 != (__tree_node_base *)0x0);
      if ((pp_Var24 == &DAT_02dbb0a0) || ((int)uVar4 < *(int *)((long)pp_Var24 + 0x20)))
      goto LAB_001d79bb;
      std::string::append((char *)&local_68);
    }
    if (puVar5[1] - 3 < 2) {
      lVar17 = *(long *)(puVar5 + 0x1e);
      if (lVar17 == 0) {
        std::string::append((char *)&local_68);
      }
      else {
        stl_printf((char *)&local_48," @ %s/%s",*(undefined8 *)(lVar17 + 0x60),lVar17 + 0x54);
        pcVar16 = local_38;
        if ((local_48 & 1) == 0) {
          pcVar16 = (char *)((long)&local_48 + 1);
        }
        std::string::append((char *)&local_68,(ulong)pcVar16);
        if ((local_48 & 1) != 0) {
          operator_delete(local_38);
        }
      }
      pcVar16 = "Runway is null!";
      if (*(long *)(puVar5 + 0x28) != 0) {
        pcVar16 = (char *)runway_spec_t::to_string((runway_spec_t *)(puVar5 + 0x28));
      }
      stl_printf((char *)&local_48," rwy %s",pcVar16);
      pcVar16 = local_38;
      if ((local_48 & 1) == 0) {
        pcVar16 = (char *)((long)&local_48 + 1);
      }
      std::string::append((char *)&local_68,(ulong)pcVar16);
      goto LAB_001d7c30;
    }
    break;
  case 6:
    std::string::append((char *)&local_68);
    stl_printf((char *)&local_48,", veczone = %d ",(ulong)puVar5[0x20]);
    pcVar16 = local_38;
    if ((local_48 & 1) == 0) {
      pcVar16 = (char *)((long)&local_48 + 1);
    }
    std::string::append((char *)&local_68,(ulong)pcVar16);
    goto LAB_001d7c30;
  case 7:
    if (DAT_02dbb0c0 == (__tree_node_base *)0x0) {
LAB_001d78db:
      std::string::append((char *)&local_68);
    }
    else {
      uVar4 = puVar5[2];
      pp_Var24 = &DAT_02dbb0c0;
      p_Var12 = DAT_02dbb0c0;
      do {
        if ((int)uVar4 <= *(int *)(p_Var12 + 0x20)) {
          pp_Var24 = (__tree_node_base **)p_Var12;
        }
        p_Var12 = *(__tree_node_base **)
                   (p_Var12 + (ulong)(*(int *)(p_Var12 + 0x20) < (int)uVar4) * 8);
      } while (p_Var12 != (__tree_node_base *)0x0);
      if ((pp_Var24 == &DAT_02dbb0c0) || ((int)uVar4 < *(int *)((long)pp_Var24 + 0x20)))
      goto LAB_001d78db;
      std::string::append((char *)&local_68);
    }
    lVar17 = *(long *)(puVar5 + 0x1e);
    if (lVar17 == 0) {
      std::string::append((char *)&local_68);
    }
    else {
      stl_printf((char *)&local_48," @ %s/%s",*(undefined8 *)(lVar17 + 0x60),lVar17 + 0x54);
      pcVar16 = local_38;
      if ((local_48 & 1) == 0) {
        pcVar16 = (char *)((long)&local_48 + 1);
      }
      std::string::append((char *)&local_68,(ulong)pcVar16);
      if ((local_48 & 1) != 0) {
        operator_delete(local_38);
      }
    }
    pcVar16 = "Runway is null!";
    if (*(long *)(puVar5 + 0x28) != 0) {
      pcVar16 = (char *)runway_spec_t::to_string((runway_spec_t *)(puVar5 + 0x28));
    }
    stl_printf((char *)&local_48," rwy %s",pcVar16);
    pcVar16 = local_38;
    if ((local_48 & 1) == 0) {
      pcVar16 = (char *)((long)&local_48 + 1);
    }
    std::string::append((char *)&local_68,(ulong)pcVar16);
    goto LAB_001d7c30;
  case 8:
    std::string::append((char *)&local_68);
    break;
  default:
    stl_printf((char *)&local_48,"!!! Unknown segment type %d");
    pcVar16 = local_38;
    if ((local_48 & 1) == 0) {
      pcVar16 = (char *)((long)&local_48 + 1);
    }
    std::string::append((char *)&local_68,(ulong)pcVar16);
LAB_001d7c30:
    if ((local_48 & 1) != 0) {
      operator_delete(local_38);
    }
  }
  std::operator+((string *)&local_48,(char *)&local_68);
  pcVar16 = (char *)((long)&local_48 + 1);
  if ((local_48 & 1) != 0) {
    pcVar16 = local_38;
  }
  (*param_1)(param_2,pcVar16,extraout_DL_01);
  if ((local_48 & 1) != 0) {
    operator_delete(local_38);
  }
  lVar17 = *(long *)(puVar5 + 6);
  if (lVar17 != 0) {
    if ((*(byte *)(lVar17 + 0x38) & 1) == 0) {
      lVar17 = lVar17 + 0x39;
    }
    else {
      lVar17 = *(long *)(lVar17 + 0x48);
    }
    stl_printf((char *)&local_48,"      Procedure: %s",lVar17);
    if ((local_68 & 1) != 0) {
      operator_delete(local_58);
    }
    local_58 = local_38;
    local_68 = CONCAT44(CONCAT13(uStack_41,CONCAT12(uStack_42,CONCAT11(uStack_43,uStack_44))),
                        local_48);
    uStack_60 = CONCAT44(uStack_3c,uStack_40);
    if ((char)puVar5[10] != '\0') {
      stl_printf((char *)&local_48,", always speak");
      pcVar16 = local_38;
      if ((local_48 & 1) == 0) {
        pcVar16 = (char *)((long)&local_48 + 1);
      }
      std::string::append((char *)&local_68,(ulong)pcVar16);
      if ((local_48 & 1) != 0) {
        operator_delete(local_38);
      }
    }
    std::operator+((string *)&local_48,(char *)&local_68);
    pcVar16 = (char *)((long)&local_48 + 1);
    if ((local_48 & 1) != 0) {
      pcVar16 = local_38;
    }
    (*param_1)(param_2,pcVar16,extraout_DL_02);
    if ((local_48 & 1) != 0) {
      operator_delete(local_38);
    }
  }
  lVar17 = *(long *)(puVar5 + 0x3e);
  if (lVar17 != 0) {
    if ((*(byte *)(lVar17 + 0x18) & 1) == 0) {
      lVar18 = lVar17 + 0x19;
    }
    else {
      lVar18 = *(long *)(lVar17 + 0x28);
    }
    stl_printf((char *)&local_48,"      Taxi seg: %s, %x ",lVar18,(ulong)*(uint *)(lVar17 + 0x30));
    if ((local_68 & 1) != 0) {
      operator_delete(local_58);
    }
    local_58 = local_38;
    local_68 = CONCAT17(uStack_41,
                        CONCAT16(uStack_42,CONCAT15(uStack_43,CONCAT14(uStack_44,local_48))));
    uStack_60 = CONCAT44(uStack_3c,uStack_40);
    if ((*(byte *)(*(long *)(puVar5 + 0x3e) + 0x31) & 2) != 0) {
      uVar10 = runway_spec_t::to_string((runway_spec_t *)(*(long *)(puVar5 + 0x3e) + 0x50));
      stl_printf((char *)&local_48," rwy %s",uVar10);
      pcVar16 = local_38;
      if ((local_48 & 1) == 0) {
        pcVar16 = (char *)((long)&local_48 + 1);
      }
      std::string::append((char *)&local_68,(ulong)pcVar16);
      if ((local_48 & 1) != 0) {
        operator_delete(local_38);
      }
    }
    std::operator+((string *)&local_48,(char *)&local_68);
    pcVar16 = (char *)((long)&local_48 + 1);
    if ((local_48 & 1) != 0) {
      pcVar16 = local_38;
    }
    (*param_1)(param_2,pcVar16,extraout_DL_03);
    if ((local_48 & 1) != 0) {
      operator_delete(local_38);
    }
    lVar17 = *(long *)(puVar5 + 0x3e);
    plVar13 = *(long **)(lVar17 + 0x60);
    while (plVar7 = plVar13, plVar7 != (long *)(lVar17 + 0x68)) {
      uVar8 = runway_spec_t::to_string((runway_spec_t *)(plVar7 + 4));
      (*param_1)(param_2,"      %s -> %x\n",uVar8);
      plVar6 = (long *)plVar7[1];
      if ((long *)plVar7[1] == (long *)0x0) {
        plVar13 = (long *)plVar7[2];
        if (*(long **)plVar7[2] != plVar7) {
          do {
            plVar7 = (long *)plVar7[2];
            plVar13 = (long *)plVar7[2];
          } while (*(long **)plVar7[2] != plVar7);
        }
      }
      else {
        do {
          plVar13 = plVar6;
          plVar6 = (long *)*plVar13;
        } while (plVar6 != (long *)0x0);
      }
    }
  }
  lVar17 = *(long *)(puVar5 + 0x22);
  lVar18 = *(long *)(puVar5 + 0x24);
  pUVar11 = (UTL_geoid *)REN_geoid::instance();
  pGVar1 = (GeoPoint2D *)(lVar18 + 0x40);
  pGVar19 = (GeoPoint2D *)(lVar17 + 0x40);
  dVar29 = *(double *)pGVar1;
  dVar31 = *(double *)pGVar19;
  if ((dVar29 != dVar31) || (NAN(dVar29) || NAN(dVar31))) {
LAB_001d7e8e:
    if (dVar29 == DAT_0253ae78) {
      if ((dVar31 == DAT_0253ae78) && (!NAN(dVar31) && !NAN(DAT_0253ae78))) goto LAB_001d7ee0;
    }
    if (dVar29 == DAT_0253ae80) {
      if ((dVar31 == DAT_0253ae80) && (!NAN(dVar31) && !NAN(DAT_0253ae80))) goto LAB_001d7ee0;
    }
    fVar27 = (float)ATCGeomDistBetweenLonLatPts(pUVar11,pGVar1,pGVar19);
    pGVar19 = extraout_RDX_00;
    if ((double)fVar27 < DAT_0253ae88) goto LAB_001d7ee0;
    REN_geoid::instance();
    local_90 = (int *)(*(double *)(*(long *)(puVar5 + 0x24) + 0x40) * DAT_0253ae48);
    local_88 = (__tree_node_base *)(*(double *)(*(long *)(puVar5 + 0x22) + 0x40) * DAT_0253ae48);
    local_a0 = *(double *)(*(long *)(puVar5 + 0x24) + 0x48) * DAT_0253ae50;
    dVar3 = *(double *)(*(long *)(puVar5 + 0x22) + 0x48) * DAT_0253ae50;
    local_70 = (double)_cos((int)local_90);
    uVar30 = SUB84(DAT_02520410,0);
    uVar28 = (undefined4)((ulong)DAT_02520410 >> 0x20);
    dVar29 = (double)_sin(SUB84(((double)local_90 - (double)local_88) * DAT_02520410,0));
    local_98 = (double)((float)dVar29 * (float)dVar29);
    dVar29 = (double)_cos((int)local_88);
    dVar29 = dVar29 * local_70;
    dVar31 = (double)_sin(SUB84((local_a0 - dVar3) * DAT_02520410,0));
    dVar29 = (double)_asin(SUB84(SQRT((double)((float)dVar31 * (float)dVar31) * dVar29 + local_98),0
                                ));
    dVar29 = dVar29 + dVar29;
    uVar8 = extraout_DL_04;
    if ((dVar29 != DAT_025252a0) || (NAN(dVar29) || NAN(DAT_025252a0))) {
      local_98 = dVar29;
      if (DAT_0253ae58 <= local_70) {
        local_a0 = (double)_sin(SUB84(dVar3 - local_a0,0));
        local_88 = (__tree_node_base *)_sin((int)local_88);
        local_90 = (int *)_sin((int)local_90);
        dVar29 = (double)___sincos_stret(SUB84(local_98,0));
        dVar31 = ((double)local_88 - (double)CONCAT44(uVar28,uVar30) * (double)local_90) /
                 (local_70 * dVar29);
        dVar29 = DAT_02520b70;
        if (dVar31 <= DAT_02520b70) {
          dVar29 = dVar31;
        }
        dVar31 = (double)_acos(-(uint)(dVar31 < DAT_02520bb0) & SUB84(DAT_02520bb0,0) |
                               ~-(uint)(dVar31 < DAT_02520bb0) & SUB84(dVar29,0));
        uVar28 = SUB84(dVar31,0);
        dVar29 = (double)((ulong)dVar31 & 0xffffffff00000000);
        uVar8 = extraout_DL_05;
        if (0.0 <= local_a0) {
          dVar29 = DAT_0253ae60 - dVar31;
          uVar28 = SUB84(dVar29,0);
        }
      }
      else {
        uVar28 = (undefined4)
                 *(undefined8 *)(&DAT_0253aac0 + (ulong)(DAT_025252a0 < (double)local_90) * 8);
        dVar29 = (double)CONCAT44((int)((ulong)*(undefined8 *)
                                                (&DAT_0253aac0 +
                                                (ulong)(DAT_025252a0 < (double)local_90) * 8) >>
                                       0x20),uVar30);
      }
      for (fVar27 = (float)((double)CONCAT44((int)((ulong)dVar29 >> 0x20),uVar28) * DAT_0253ae68);
          fVar27 < 0.0; fVar27 = fVar27 + DAT_02520bc4) {
      }
      for (; DAT_02520bc4 < fVar27; fVar27 = fVar27 + DAT_02520bd8) {
      }
      for (; fVar27 < 0.0; fVar27 = fVar27 + DAT_02520bc4) {
      }
      for (; DAT_02520bc4 < fVar27; fVar27 = fVar27 + DAT_02520bd8) {
      }
    }
    (*param_1)(param_2,"    Heading %.03f, Length %.1f meters / %.1f NM\n",uVar8);
  }
  else {
    dVar3 = *(double *)(lVar18 + 0x48);
    pdVar2 = (double *)(lVar17 + 0x48);
    if ((dVar3 != *pdVar2) || (NAN(dVar3) || NAN(*pdVar2))) goto LAB_001d7e8e;
LAB_001d7ee0:
    (*param_1)(param_2,"    <zero-length segment>\n",(char)pGVar19);
  }
  if ((7 < *puVar5) || ((0xb8U >> (*puVar5 & 0x1f) & 1) == 0)) goto LAB_001d7450;
  if ((char)puVar5[0x30] == '\0') {
    uStack_43 = 0x74;
    local_48 = 0x736e550a;
    uStack_44 = 0x65;
    uStack_42 = 0;
    if ((char)puVar5[0x32] != '\0') goto LAB_001d7f6b;
LAB_001d820a:
    local_f0 = 10;
    local_eb = 0x74;
    local_ef = 0x65736e55;
    local_ea = 0;
    if ((char)puVar5[0x30] != '\0') goto LAB_001d7fbb;
LAB_001d8237:
    local_d8 = 10;
    local_d3 = 0x74;
    local_d7 = 0x65736e55;
    local_d2 = 0;
    if ((char)puVar5[0x32] != '\0') goto LAB_001d7feb;
LAB_001d8264:
    local_c0 = 10;
    local_bb = 0x74;
    local_bf = 0x65736e55;
    local_ba = 0;
    cVar14 = (char)&local_48;
  }
  else {
    stl_printf((char *)&local_48,"%d",
               (ulong)(uint)(int)((((float)puVar5[0x2f] * DAT_02525330 * DAT_02525330) /
                                  DAT_02536f14) / DAT_02536f10));
    if ((char)puVar5[0x32] == '\0') goto LAB_001d820a;
LAB_001d7f6b:
    stl_printf((char *)&local_f0,"%d",
               (ulong)(uint)(int)((((float)puVar5[0x31] * DAT_02525330 * DAT_02525330) /
                                  DAT_02536f14) / DAT_02536f10));
    if ((char)puVar5[0x30] == '\0') goto LAB_001d8237;
LAB_001d7fbb:
    stl_printf((char *)&local_d8,SUB84((double)(float)puVar5[0x2f],0),"%.1f");
    if ((char)puVar5[0x32] == '\0') goto LAB_001d8264;
LAB_001d7feb:
    stl_printf((char *)&local_c0,SUB84((double)(float)puVar5[0x31],0),"%.1f");
    cVar14 = (char)&local_48;
  }
  cVar14 = cVar14 + '\x01';
  if ((local_48 & 1) != 0) {
    cVar14 = (char)local_38;
  }
  (*param_1)(param_2,"    Altitude Min/Max %s/%s ft (%s/%s m) %s, Block type = %d\n",cVar14);
  if ((local_c0 & 1) != 0) {
    operator_delete(local_b0);
  }
  if ((local_d8 & 1) != 0) {
    operator_delete(local_c8);
  }
  if ((local_f0 & 1) != 0) {
    operator_delete(local_e0);
  }
  if ((local_48 & 1) != 0) {
    operator_delete(local_38);
  }
LAB_001d7450:
  uVar15 = (ulong)(local_a4 + 1);
  lVar17 = lVar22;
  if (lVar22 == 0) goto LAB_001d8e23;
  goto LAB_001d7462;
LAB_001d8c3f:
  ___cxa_atexit(std::
                map<ATCIFRSubtype,char_const*,std::less<ATCIFRSubtype>,std::allocator<std::pair<ATCIFRSubtype_const,char_const*>>>
                ::~map,&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kIFRNavNames
                ,0x10000);
  ___cxa_guard_release
            (&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kIFRNavNames);
  goto LAB_001d76a8;
LAB_001d8c6a:
  ___cxa_atexit(std::
                map<ATCVecSubtype,char_const*,std::less<ATCVecSubtype>,std::allocator<std::pair<ATCVecSubtype_const,char_const*>>>
                ::~map,&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                        kVectorNavNames,0x10000);
  ___cxa_guard_release
            (&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kVectorNavNames);
  goto LAB_001d76b6;
LAB_001d8c95:
  ___cxa_atexit(std::
                map<ATCRwySubtype,char_const*,std::less<ATCRwySubtype>,std::allocator<std::pair<ATCRwySubtype_const,char_const*>>>
                ::~map,&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::
                        kRunwayNavNames,0x10000);
  ___cxa_guard_release
            (&PrintRoutingWithFunc(int(*)(void*,char_const*,...),void*,bool)::kRunwayNavNames);
  goto LAB_001d76c4;
}


// 001d9ab0  ATCFlightSegment::~ATCFlightSegment

/* ATCFlightSegment::~ATCFlightSegment() */

void __thiscall ATCFlightSegment::~ATCFlightSegment(ATCFlightSegment *this)

{
  long *plVar1;
  long lVar2;
  ATCFlightSegment AVar3;
  long *plVar4;
  
  if (*(ATCNetwork_halfedge **)(this + 0xf8) != (ATCNetwork_halfedge *)0x0) {
    ATCNetwork_halfedge::rem_occupier(*(ATCNetwork_halfedge **)(this + 0xf8),this);
  }
  if (((byte)this[0x60] & 1) == 0) {
    AVar3 = this[0x48];
  }
  else {
    operator_delete(*(void **)(this + 0x70));
    AVar3 = this[0x48];
  }
  if (((byte)AVar3 & 1) == 0) {
    AVar3 = this[0x30];
  }
  else {
    operator_delete(*(void **)(this + 0x58));
    AVar3 = this[0x30];
  }
  if (((byte)AVar3 & 1) == 0) {
    plVar4 = *(long **)(this + 0x20);
  }
  else {
    operator_delete(*(void **)(this + 0x40));
    plVar4 = *(long **)(this + 0x20);
  }
  if (plVar4 != (long *)0x0) {
    LOCK();
    plVar1 = plVar4 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar4 + 0x10))(plVar4);
      std::__shared_weak_count::__release_weak();
      return;
    }
  }
  return;
}


// 001d9bc0  ATCFlightSegment::Copy

/* ATCFlightSegment::Copy(ATCFlightSegment*, ATCFlightSegment const&) */

void ATCFlightSegment::Copy(ATCFlightSegment *param_1,ATCFlightSegment *param_2)

{
  long *plVar1;
  undefined8 uVar2;
  long lVar3;
  long *plVar4;
  ATCNetwork_halfedge *this;
  
  if (*(ATCNetwork_halfedge **)(param_1 + 0xf8) != (ATCNetwork_halfedge *)0x0) {
    ATCNetwork_halfedge::rem_occupier(*(ATCNetwork_halfedge **)(param_1 + 0xf8),param_1);
  }
  *(undefined8 *)(param_1 + 0x98) = *(undefined8 *)(param_2 + 0x98);
  uVar2 = *(undefined8 *)(param_2 + 8);
  *(undefined8 *)param_1 = *(undefined8 *)param_2;
  *(undefined8 *)(param_1 + 8) = uVar2;
  *(undefined4 *)(param_1 + 0x10) = *(undefined4 *)(param_2 + 0x10);
  std::string::operator=((string *)(param_1 + 0x30),(string *)(param_2 + 0x30));
  std::string::operator=((string *)(param_1 + 0x48),(string *)(param_2 + 0x48));
  std::string::operator=((string *)(param_1 + 0x60),(string *)(param_2 + 0x60));
  *(undefined8 *)(param_1 + 0x78) = *(undefined8 *)(param_2 + 0x78);
  *(undefined8 *)(param_1 + 0xa0) = *(undefined8 *)(param_2 + 0xa0);
  param_1[0xa8] = param_2[0xa8];
  param_1[0xb0] = param_2[0xb0];
  uVar2 = *(undefined8 *)(param_2 + 0x18);
  lVar3 = *(long *)(param_2 + 0x20);
  if (lVar3 != 0) {
    LOCK();
    *(long *)(lVar3 + 8) = *(long *)(lVar3 + 8) + 1;
    UNLOCK();
  }
  *(undefined8 *)(param_1 + 0x18) = uVar2;
  plVar4 = *(long **)(param_1 + 0x20);
  *(long *)(param_1 + 0x20) = lVar3;
  if (plVar4 != (long *)0x0) {
    LOCK();
    plVar1 = plVar4 + 1;
    lVar3 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar3 == 0) {
      (**(code **)(*plVar4 + 0x10))(plVar4);
      std::__shared_weak_count::__release_weak();
    }
  }
  param_1[0x28] = param_2[0x28];
  *(undefined4 *)(param_1 + 0x80) = *(undefined4 *)(param_2 + 0x80);
  this = *(ATCNetwork_halfedge **)(param_2 + 0xf8);
  *(ATCNetwork_halfedge **)(param_1 + 0xf8) = this;
  *(undefined4 *)(param_1 + 0xb8) = *(undefined4 *)(param_2 + 0xb8);
  param_1[0xc0] = param_2[0xc0];
  *(undefined4 *)(param_1 + 0xbc) = *(undefined4 *)(param_2 + 0xbc);
  *(undefined4 *)(param_1 + 0xc4) = *(undefined4 *)(param_2 + 0xc4);
  param_1[200] = param_2[200];
  param_1[0xe0] = param_2[0xe0];
  *(undefined4 *)(param_1 + 0xcc) = *(undefined4 *)(param_2 + 0xcc);
  param_1[0xd4] = param_2[0xd4];
  *(undefined4 *)(param_1 + 0xd0) = *(undefined4 *)(param_2 + 0xd0);
  *(undefined4 *)(param_1 + 0xd8) = *(undefined4 *)(param_2 + 0xd8);
  param_1[0xdc] = param_2[0xdc];
  param_1[0xe8] = param_2[0xe8];
  *(undefined4 *)(param_1 + 0xe4) = *(undefined4 *)(param_2 + 0xe4);
  *(undefined4 *)(param_1 + 0xec) = *(undefined4 *)(param_2 + 0xec);
  param_1[0xf0] = param_2[0xf0];
  param_1[0x84] = param_2[0x84];
  param_1[0x85] = param_2[0x85];
  if (this != (ATCNetwork_halfedge *)0x0) {
    ATCNetwork_halfedge::add_occupier(this,param_1);
    return;
  }
  return;
}


// 001d9dc0  ATCFlightSegment::ATCFlightSegment

/* ATCFlightSegment::ATCFlightSegment(ATCFlightSegment const&) */

void __thiscall ATCFlightSegment::ATCFlightSegment(ATCFlightSegment *this,ATCFlightSegment *param_1)

{
  undefined8 uVar1;
  
  *(undefined8 *)this = 0;
  *(undefined8 *)(this + 8) = 0;
  *(undefined4 *)(this + 0x10) = 0;
  *(undefined8 *)(this + 0x18) = 0;
  *(undefined8 *)(this + 0x20) = 0;
  this[0x28] = (ATCFlightSegment)0x0;
  *(undefined8 *)(this + 0x30) = 0;
  *(undefined8 *)(this + 0x38) = 0;
  *(undefined8 *)(this + 0x40) = 0;
  *(undefined8 *)(this + 0x48) = 0;
  *(undefined8 *)(this + 0x50) = 0;
  *(undefined8 *)(this + 0x58) = 0;
  *(undefined8 *)(this + 0x60) = 0;
  *(undefined8 *)(this + 0x68) = 0;
  *(undefined8 *)(this + 0x70) = 0;
  *(undefined8 *)(this + 0x78) = 0;
  *(undefined4 *)(this + 0x80) = 0xfffffffe;
  *(undefined2 *)(this + 0x84) = 0;
  this[0xb0] = (ATCFlightSegment)0x0;
  *(undefined8 *)(this + 0x88) = 0;
  *(undefined8 *)(this + 0x90) = 0;
  *(undefined8 *)(this + 0x98) = 0;
  *(undefined8 *)(this + 0xa0) = 0;
  this[0xa8] = (ATCFlightSegment)0x0;
  *(undefined4 *)(this + 0xb8) = 0xffffffff;
  this[0xbc] = (ATCFlightSegment)0x0;
  this[0xc0] = (ATCFlightSegment)0x0;
  this[0xc4] = (ATCFlightSegment)0x0;
  this[200] = (ATCFlightSegment)0x0;
  *(undefined4 *)(this + 0xcc) = 0xffffffff;
  this[0xd0] = (ATCFlightSegment)0x0;
  this[0xd4] = (ATCFlightSegment)0x0;
  this[0xd8] = (ATCFlightSegment)0x0;
  this[0xdc] = (ATCFlightSegment)0x0;
  this[0xe0] = (ATCFlightSegment)0x0;
  this[0xe4] = (ATCFlightSegment)0x0;
  this[0xe8] = (ATCFlightSegment)0x0;
  this[0xec] = (ATCFlightSegment)0x0;
  this[0xf0] = (ATCFlightSegment)0x0;
  *(undefined8 *)(this + 0xf8) = 0;
  Copy(this,param_1);
  uVar1 = *(undefined8 *)(param_1 + 0x90);
  *(undefined8 *)(this + 0x88) = *(undefined8 *)(param_1 + 0x88);
  *(undefined8 *)(this + 0x90) = uVar1;
  return;
}


// 001d9f00  ATCFlightSegment::operator=

/* ATCFlightSegment::TEMPNAMEPLACEHOLDERVALUE(ATCFlightSegment const&) */

ATCFlightSegment * __thiscall
ATCFlightSegment::operator=(ATCFlightSegment *this,ATCFlightSegment *param_1)

{
  undefined8 uVar1;
  
  Copy(this,param_1);
  uVar1 = *(undefined8 *)(param_1 + 0x90);
  *(undefined8 *)(this + 0x88) = *(undefined8 *)(param_1 + 0x88);
  *(undefined8 *)(this + 0x90) = uVar1;
  return this;
}


// 001d9f30  ATCFlightSegment::SetUnderlying

/* ATCFlightSegment::SetUnderlying(ATCNetwork_halfedge const*) */

void __thiscall ATCFlightSegment::SetUnderlying(ATCFlightSegment *this,ATCNetwork_halfedge *param_1)

{
  if (*(ATCNetwork_halfedge **)(this + 0xf8) != (ATCNetwork_halfedge *)0x0) {
    ATCNetwork_halfedge::rem_occupier(*(ATCNetwork_halfedge **)(this + 0xf8),this);
  }
  *(ATCNetwork_halfedge **)(this + 0xf8) = param_1;
  if (param_1 != (ATCNetwork_halfedge *)0x0) {
    ATCNetwork_halfedge::add_occupier(param_1,this);
    return;
  }
  return;
}


// 001f6b70  ATCFlightRouteUtils::GetFirstSegOfType

/* ATCFlightRouteUtils::GetFirstSegOfType(ATCFlightRoute const&, ATCFlightSegmentType,
   ATCFlightSegment const*) */

int * ATCFlightRouteUtils::GetFirstSegOfType(long *param_1,int param_2,int *param_3)

{
  if ((*param_1 != 0) && (param_1[1] != 0)) {
    if (param_3 != (int *)0x0) goto LAB_001f6ba0;
    for (param_3 = *(int **)(*param_1 + 0x90); param_3 != (int *)0x0;
        param_3 = *(int **)(*(long *)(param_3 + 0x22) + 0x90)) {
LAB_001f6ba0:
      if (*param_3 == param_2) {
        return param_3;
      }
      if (*(long *)(param_3 + 0x22) == 0) {
        return (int *)0x0;
      }
    }
  }
  return (int *)0x0;
}


// 001f6bc0  ATCFlightRouteUtils::GetFirstNonGroundHoldSeg

/* ATCFlightRouteUtils::GetFirstNonGroundHoldSeg(ATCFlightRoute&) */

int * ATCFlightRouteUtils::GetFirstNonGroundHoldSeg(ATCFlightRoute *param_1)

{
  int *piVar1;
  
  if ((*(long *)param_1 != 0) && (*(long *)(param_1 + 8) != 0)) {
    for (piVar1 = *(int **)(*(long *)param_1 + 0x90); piVar1 != (int *)0x0;
        piVar1 = *(int **)(*(long *)(piVar1 + 0x22) + 0x90)) {
      if (*piVar1 != 1) {
        return piVar1;
      }
      if (*(long *)(piVar1 + 0x22) == 0) {
        return (int *)0x0;
      }
    }
  }
  return (int *)0x0;
}


// 001f6c20  ATCFlightRouteUtils::GetFirstNonTaxiSeg

/* ATCFlightRouteUtils::GetFirstNonTaxiSeg(ATCFlightRoute&) */

int * ATCFlightRouteUtils::GetFirstNonTaxiSeg(ATCFlightRoute *param_1)

{
  int *piVar1;
  
  if ((*(long *)param_1 != 0) && (*(long *)(param_1 + 8) != 0)) {
    for (piVar1 = *(int **)(*(long *)param_1 + 0x90); piVar1 != (int *)0x0;
        piVar1 = *(int **)(*(long *)(piVar1 + 0x22) + 0x90)) {
      if (1 < *piVar1 - 1U) {
        return piVar1;
      }
      if (*(long *)(piVar1 + 0x22) == 0) {
        return (int *)0x0;
      }
    }
  }
  return (int *)0x0;
}


// 001f6c80  ATCFlightRouteUtils::GetFirstNonFlyableSeg

/* ATCFlightRouteUtils::GetFirstNonFlyableSeg(ATCFlightRoute&) */

uint * ATCFlightRouteUtils::GetFirstNonFlyableSeg(ATCFlightRoute *param_1)

{
  uint *puVar1;
  
  if ((*(long *)param_1 != 0) && (*(long *)(param_1 + 8) != 0)) {
    for (puVar1 = *(uint **)(*(long *)param_1 + 0x90); puVar1 != (uint *)0x0;
        puVar1 = *(uint **)(*(long *)(puVar1 + 0x22) + 0x90)) {
      if (((8 < *puVar1) || ((0x198U >> (*puVar1 & 0x1f) & 1) == 0)) &&
         ((puVar1[2] & 0xfffffffe) != 6)) {
        return puVar1;
      }
      if (*(long *)(puVar1 + 0x22) == 0) {
        return (uint *)0x0;
      }
    }
  }
  return (uint *)0x0;
}


// 001f6d00  ATCFlightRouteUtils::GetFirstZoneVectorSeg

/* ATCFlightRouteUtils::GetFirstZoneVectorSeg(ATCFlightRoute&) */

int * ATCFlightRouteUtils::GetFirstZoneVectorSeg(ATCFlightRoute *param_1)

{
  int *piVar1;
  
  if ((*(long *)param_1 != 0) && (*(long *)(param_1 + 8) != 0)) {
    for (piVar1 = *(int **)(*(long *)param_1 + 0x90); piVar1 != (int *)0x0;
        piVar1 = *(int **)(*(long *)(piVar1 + 0x22) + 0x90)) {
      if ((*piVar1 == 5) && (piVar1[1] - 3U < 2)) {
        return piVar1;
      }
      if (*(long *)(piVar1 + 0x22) == 0) {
        return (int *)0x0;
      }
    }
  }
  return (int *)0x0;
}


// 001f6d60  ATCFlightRouteUtils::GetDepartureRunwaySeg

/* ATCFlightRouteUtils::GetDepartureRunwaySeg(ATCFlightRoute&) */

int * ATCFlightRouteUtils::GetDepartureRunwaySeg(ATCFlightRoute *param_1)

{
  int *piVar1;
  
  if ((*(long *)param_1 != 0) && (*(long *)(param_1 + 8) != 0)) {
    for (piVar1 = *(int **)(*(long *)param_1 + 0x90); piVar1 != (int *)0x0;
        piVar1 = *(int **)(*(long *)(piVar1 + 0x22) + 0x90)) {
      if ((*piVar1 == 7) && (piVar1[2] == 1)) {
        return piVar1;
      }
      if (*(long *)(piVar1 + 0x22) == 0) {
        return (int *)0x0;
      }
    }
  }
  return (int *)0x0;
}


// 001f6dc0  ATCFlightRouteUtils::FindClearedAltitude

/* ATCFlightRouteUtils::FindClearedAltitude(ATCAircraft const*, ATCAircraftFlightPlan const&, char
   const*) */

ulong ATCFlightRouteUtils::FindClearedAltitude
                (ATCAircraft *param_1,ATCAircraftFlightPlan *param_2,char *param_3)

{
  int iVar1;
  uint uVar2;
  long lVar3;
  bool bVar4;
  int iVar5;
  int *piVar6;
  size_t sVar7;
  ulong uVar8;
  size_t sVar9;
  ulong uVar10;
  uint uVar11;
  int *piVar12;
  int *piVar13;
  float *pfVar14;
  uint uVar15;
  char cVar16;
  undefined1 local_34;
  
  iVar1 = *(int *)param_2;
  uVar2 = *(uint *)(param_2 + 0xa0);
  uVar11 = 0;
  if (iVar1 == 2) {
    uVar11 = uVar2;
  }
  piVar6 = (int *)ATCAircraft::GetCurrentSegment(param_1);
  if (piVar6 != (int *)0x0) {
    if (param_3 == (char *)0x0) {
      piVar13 = (int *)0x0;
LAB_001f7000:
      piVar12 = piVar6;
      if ((*piVar6 - 3U < 6) && (((char)piVar6[10] != '\0' || (*(long *)(piVar6 + 6) == 0)))) {
        cVar16 = (char)piVar6[0x30];
        if (cVar16 == '\0') {
          if ((char)piVar6[0x32] != '\0') {
            uVar15 = piVar6[0x2e];
            if (uVar15 != 3) goto LAB_001f7035;
            goto LAB_001f70d3;
          }
          goto LAB_001f7140;
        }
        uVar15 = piVar6[0x2e];
LAB_001f7035:
        if ((uVar15 == 2) && ((char)piVar6[0x32] == '\0')) {
LAB_001f70d3:
          lVar3 = *(long *)(piVar6 + 0x22);
          goto joined_r0x001f70e0;
        }
        if (((*(long *)(piVar6 + 6) == 0) || (piVar13 == (int *)0x0)) || (piVar13[0x2e] != uVar15))
        goto LAB_001f6fc1;
        bVar4 = (cVar16 != '\0') != ((char)piVar13[0x30] != '\0');
        if ((bVar4) || ((char)piVar13[0x30] == '\0')) {
          if (bVar4) goto LAB_001f6fc1;
        }
        else if (((float)piVar13[0x2f] != (float)piVar6[0x2f]) ||
                (NAN((float)piVar13[0x2f]) || NAN((float)piVar6[0x2f]))) goto LAB_001f6fc1;
        bVar4 = ((char)piVar6[0x32] != '\0') != ((char)piVar13[0x32] != '\0');
        piVar12 = piVar13;
        if ((!bVar4) && ((char)piVar13[0x32] != '\0')) {
          if (((float)piVar13[0x31] == (float)piVar6[0x31]) &&
             (!NAN((float)piVar13[0x31]) && !NAN((float)piVar6[0x31]))) goto LAB_001f7140;
          goto LAB_001f6fc1;
        }
        if (bVar4) goto LAB_001f6fc1;
      }
LAB_001f7140:
      lVar3 = *(long *)(piVar6 + 0x22);
      piVar13 = piVar12;
joined_r0x001f70e0:
      if ((lVar3 == 0) || (piVar6 = *(int **)(lVar3 + 0x90), piVar6 == (int *)0x0))
      goto LAB_001f715f;
      goto LAB_001f7000;
    }
    piVar13 = (int *)0x0;
    do {
      piVar12 = piVar6;
      if ((*piVar6 - 3U < 6) && (lVar3 = *(long *)(piVar6 + 6), lVar3 != 0)) {
        sVar7 = _strlen(param_3);
        if ((*(byte *)(lVar3 + 0x38) & 1) == 0) {
          sVar9 = (size_t)(*(byte *)(lVar3 + 0x38) >> 1);
        }
        else {
          sVar9 = *(size_t *)(lVar3 + 0x40);
        }
        if (((sVar7 == sVar9) &&
            (iVar5 = std::string::compare(lVar3 + 0x38,0,(char *)0xffffffffffffffff,(ulong)param_3),
            iVar5 == 0)) && (((char)piVar6[10] != '\0' || (*(long *)(piVar6 + 6) == 0)))) {
          cVar16 = (char)piVar6[0x30];
          if (cVar16 == '\0') {
            if (((char)piVar6[0x32] == '\0') ||
               (uVar15 = piVar6[0x2e], piVar12 = piVar13, uVar15 == 3)) goto LAB_001f6e80;
          }
          else {
            uVar15 = piVar6[0x2e];
          }
          if ((uVar15 != 2) || (piVar12 = piVar13, (char)piVar6[0x32] != '\0')) {
            if ((*(long *)(piVar6 + 6) == 0) ||
               ((piVar13 == (int *)0x0 || (piVar13[0x2e] != uVar15)))) goto LAB_001f6fc1;
            bVar4 = (cVar16 != '\0') != ((char)piVar13[0x30] != '\0');
            if ((bVar4) || ((char)piVar13[0x30] == '\0')) {
              if (bVar4) goto LAB_001f6fc1;
            }
            else if (((float)piVar13[0x2f] != (float)piVar6[0x2f]) ||
                    (NAN((float)piVar13[0x2f]) || NAN((float)piVar6[0x2f]))) goto LAB_001f6fc1;
            bVar4 = ((char)piVar6[0x32] != '\0') != ((char)piVar13[0x32] != '\0');
            if ((bVar4) || ((char)piVar13[0x32] == '\0')) {
              piVar12 = piVar13;
              if (bVar4) goto LAB_001f6fc1;
            }
            else if (((float)piVar13[0x31] != (float)piVar6[0x31]) ||
                    (piVar12 = piVar13, NAN((float)piVar13[0x31]) || NAN((float)piVar6[0x31])))
            goto LAB_001f6fc1;
          }
        }
      }
LAB_001f6e80:
    } while ((*(long *)(piVar6 + 0x22) != 0) &&
            (piVar6 = *(int **)(*(long *)(piVar6 + 0x22) + 0x90), piVar13 = piVar12,
            piVar6 != (int *)0x0));
  }
LAB_001f715f:
  local_34 = (undefined1)uVar11;
  uVar8 = (ulong)CONCAT41(uVar2 >> 8,local_34);
  if (iVar1 != 2) {
    uVar10 = 0;
    goto LAB_001f7181;
  }
LAB_001f7173:
  uVar10 = 0x100000000;
LAB_001f7181:
  return uVar8 | uVar10;
LAB_001f6fc1:
  if (4 < uVar15) goto LAB_001f715f;
  pfVar14 = (float *)(piVar6 + 0x2f);
  switch(uVar15) {
  case 0:
    break;
  default:
    pfVar14 = (float *)(piVar6 + 0x31);
    break;
  case 2:
    if ((char)piVar6[0x32] != '\0') {
      pfVar14 = (float *)(piVar6 + 0x31);
    }
    break;
  case 3:
    if (cVar16 == '\0') {
      pfVar14 = (float *)(piVar6 + 0x31);
    }
  }
  uVar8 = (ulong)(uint)(((*pfVar14 * DAT_02525330 * DAT_02525330) / DAT_02536f14) / DAT_02536f10);
  goto LAB_001f7173;
}


// 001f7200  ATCFlightRouteUtils::IsQueuedBehind

/* ATCFlightRouteUtils::IsQueuedBehind(UTL_geoid const&, ATCAircraft const*, ATCAircraft const*) */

bool ATCFlightRouteUtils::IsQueuedBehind
               (UTL_geoid *param_1,ATCAircraft *param_2,ATCAircraft *param_3)

{
  long *plVar1;
  bool bVar2;
  int *piVar3;
  long lVar4;
  float extraout_XMM0_Da;
  undefined8 local_78;
  undefined8 uStack_70;
  undefined4 local_68;
  undefined4 uStack_64;
  undefined4 uStack_60;
  undefined4 uStack_5c;
  undefined8 local_50 [2];
  undefined8 local_40 [2];
  float local_2c;
  
  piVar3 = (int *)ATCAircraft::GetCurrentSegment(param_2);
  lVar4 = ATCAircraft::GetCurrentSegment(param_3);
  bVar2 = false;
  if ((piVar3 != (int *)0x0) && (lVar4 != 0)) {
    plVar1 = *(long **)(piVar3 + 0x3e);
    if (*(long **)(lVar4 + 0xf8) == plVar1) {
      lVar4 = plVar1[1];
      local_78 = *(undefined8 *)(*plVar1 + 0x68);
      uStack_70 = *(undefined8 *)(*plVar1 + 0x70);
      local_68 = *(undefined4 *)(lVar4 + 0x68);
      uStack_64 = *(undefined4 *)(lVar4 + 0x6c);
      uStack_60 = *(undefined4 *)(lVar4 + 0x70);
      uStack_5c = *(undefined4 *)(lVar4 + 0x74);
      local_50[0] = (**(code **)(*(long *)param_2 + 0x268))(param_2);
      local_2c = (float)ATCGeomRatioAlong(param_1,(GeoSegment *)&local_78,(GeoPoint2D *)local_50);
      local_40[0] = (**(code **)(*(long *)param_3 + 0x268))(param_3);
      ATCGeomRatioAlong(param_1,(GeoSegment *)&local_78,(GeoPoint2D *)local_40);
      bVar2 = local_2c < extraout_XMM0_Da;
    }
    else {
      while (*piVar3 != 5) {
        if (*(long **)(piVar3 + 0x3e) == *(long **)(lVar4 + 0xf8)) {
          return true;
        }
        if ((*(long *)(piVar3 + 0x22) == 0) ||
           (piVar3 = *(int **)(*(long *)(piVar3 + 0x22) + 0x90), piVar3 == (int *)0x0)) break;
      }
      bVar2 = false;
    }
  }
  return bVar2;
}


// 001f7320  ATCFlightRouteUtils::IsSegmentConflicted

/* ATCFlightRouteUtils::IsSegmentConflicted(UTL_geoid const&, std::shared_ptr<ATCControllerCab
   const>, ATCFlightSegment const*) */

undefined8
ATCFlightRouteUtils::IsSegmentConflicted
          (undefined8 param_1_00,undefined8 param_2,UTL_geoid *param_1,undefined8 *param_4,
          long param_5)

{
  float *pfVar1;
  long *plVar2;
  long lVar3;
  ulong uVar4;
  bool bVar5;
  bool bVar6;
  long *plVar7;
  long lVar8;
  __tree_node *p_Var9;
  int *piVar10;
  __tree_node *p_Var11;
  long *plVar12;
  long *plVar13;
  __tree_node *p_Var14;
  __tree_node *p_Var15;
  long lVar16;
  undefined4 uVar17;
  float fVar18;
  float fVar19;
  undefined4 uVar20;
  set *local_108;
  undefined8 local_100;
  long *local_f8;
  __tree_node **local_f0;
  __tree_node *local_e8;
  undefined8 uStack_e0;
  undefined8 local_d8;
  __tree_node *p_Stack_d0;
  undefined4 local_c8;
  undefined4 uStack_c4;
  undefined4 uStack_c0;
  undefined4 uStack_bc;
  __tree_node *local_b0;
  UTL_geoid *local_a8;
  undefined8 local_a0;
  __tree_node *local_98 [2];
  __tree_node *local_88;
  long local_80;
  void *local_78;
  void *pvStack_70;
  undefined8 local_68;
  __tree_node *local_60;
  __tree_node *local_58;
  undefined8 uStack_50;
  long *local_48;
  float local_40;
  float local_3c;
  undefined1 local_38 [8];
  
  uVar20 = (undefined4)((ulong)param_2 >> 0x20);
  fVar19 = (float)param_2;
  lVar3 = *(long *)(param_5 + 0xf8);
  if (lVar3 == 0) {
    return 0;
  }
  lVar16 = *(long *)(lVar3 + 0x10);
  plVar13 = *(long **)(lVar16 + 0x80);
  plVar2 = (long *)(lVar16 + 0x80);
  if (plVar13 != (long *)0x0) {
    uVar4 = *(ulong *)(param_5 + 0x98);
    plVar12 = plVar2;
    do {
      if ((ulong)plVar13[4] >= uVar4) {
        plVar12 = plVar13;
      }
      plVar13 = (long *)plVar13[(ulong)plVar13[4] < uVar4];
    } while (plVar13 != (long *)0x0);
    if ((plVar12 != plVar2) && ((ulong)plVar12[4] <= uVar4)) goto LAB_001f73a4;
  }
  plVar12 = plVar2;
LAB_001f73a4:
  if (*(ulong *)(lVar16 + 0x88) != (ulong)(plVar12 != plVar2)) {
    local_60 = (__tree_node *)&local_58;
    local_58 = (__tree_node *)0x0;
    uStack_50 = 0;
    local_a8 = param_1;
    local_80 = param_5;
    if (*(long **)(lVar16 + 0x78) != plVar2) {
      plVar13 = *(long **)(lVar16 + 0x78);
      do {
        std::
        __tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
        ::
        __emplace_hint_unique_key_args<ATCAircraft_const*,std::pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>const&>
                  ((__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
                    *)&local_60,&local_58,plVar13 + 4);
        plVar12 = (long *)plVar13[1];
        if ((long *)plVar13[1] == (long *)0x0) {
          plVar7 = (long *)plVar13[2];
          if ((long *)*plVar7 != plVar13) {
            do {
              plVar13 = (long *)plVar13[2];
              plVar7 = (long *)plVar13[2];
            } while ((long *)*plVar7 != plVar13);
          }
        }
        else {
          do {
            plVar7 = plVar12;
            plVar12 = (long *)*plVar7;
          } while ((long *)*plVar7 != (long *)0x0);
        }
        plVar13 = plVar7;
      } while (plVar7 != plVar2);
    }
    local_40 = *(float *)(*(long *)(local_80 + 0x90) + 0x38);
    local_3c = *(float *)(*(long *)(local_80 + 0x88) + 0x38);
    local_f0 = &local_e8;
    local_e8 = (__tree_node *)0x0;
    uStack_e0 = 0;
    ATCControllerCab::GetActiveRwys((ATCControllerCab *)*param_4,(set *)&local_f0);
    local_100 = *param_4;
    local_f8 = (long *)param_4[1];
    if (local_f8 != (long *)0x0) {
      LOCK();
      local_f8[1] = local_f8[1] + 1;
      UNLOCK();
    }
    local_108 = (set *)&local_f0;
    local_48 = local_f8;
    if (local_60 != (__tree_node *)&local_58) {
      local_40 = local_40 + DAT_02525304;
      local_3c = local_3c + DAT_02520298;
      p_Var14 = local_60;
      lVar16 = local_80;
      do {
        if (*(ATCAircraft **)(p_Var14 + 0x20) != *(ATCAircraft **)(lVar16 + 0x98)) {
          lVar8 = ATCAircraft::GetCurrentSegment(*(ATCAircraft **)(p_Var14 + 0x20));
          plVar2 = *(long **)(lVar8 + 0xf8);
          lVar8 = ATCAircraft::GetCurrentSegment(*(ATCAircraft **)(lVar16 + 0x98));
          if (*(long **)(lVar8 + 0xf8) == plVar2) {
            lVar8 = plVar2[1];
            local_d8 = *(undefined8 *)(*plVar2 + 0x68);
            p_Stack_d0 = *(__tree_node **)(*plVar2 + 0x70);
            local_c8 = *(undefined4 *)(lVar8 + 0x68);
            uStack_c4 = *(undefined4 *)(lVar8 + 0x6c);
            uStack_c0 = *(undefined4 *)(lVar8 + 0x70);
            uStack_bc = *(undefined4 *)(lVar8 + 0x74);
            local_78 = (void *)(**(code **)(**(long **)(lVar16 + 0x98) + 0x268))();
            pvStack_70 = (void *)CONCAT44(uVar20,fVar19);
            uVar17 = ATCGeomRatioAlong(local_a8,(GeoSegment *)&local_d8,(GeoPoint2D *)&local_78);
            local_88 = (__tree_node *)CONCAT44(local_88._4_4_,uVar17);
            local_a0 = (**(code **)(**(long **)(p_Var14 + 0x20) + 0x268))();
            local_98[0] = (__tree_node *)CONCAT44(uVar20,fVar19);
            fVar18 = (float)ATCGeomRatioAlong(local_a8,(GeoSegment *)&local_d8,
                                              (GeoPoint2D *)&local_a0);
            uVar20 = 0;
            fVar19 = local_88._0_4_;
            if (fVar18 < local_88._0_4_) goto LAB_001f77d0;
          }
          IsSegmentConflicted(UTL_geoid_const&,std::shared_ptr<ATCControllerCab_const>,ATCFlightSegment_const*)
          ::$_32::operator()((__32 *)&local_d8,(ATCNetwork_halfedge *)&local_108);
          local_88 = p_Var14 + 0x30;
          bVar5 = true;
          p_Var15 = *(__tree_node **)(p_Var14 + 0x28);
          local_b0 = p_Var14;
          do {
            if (p_Var15 == local_88) {
              std::__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>>::
              destroy((__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>>
                       *)&local_d8,p_Stack_d0);
              bVar6 = false;
              bVar5 = false;
              goto joined_r0x001f784c;
            }
            piVar10 = (int *)ATCAircraft::GetCurrentSegment(*(ATCAircraft **)(local_b0 + 0x20));
            bVar6 = bVar5;
            if ((bVar5) && (piVar10 != (int *)0x0)) {
              while ((bVar6 = bVar5, *(long *)(piVar10 + 0x3e) != *(long *)(lVar3 + 0x10) &&
                     ((bVar6 = false, *piVar10 != 1 && (*(long *)(piVar10 + 0x3e) != lVar3))))) {
                local_78 = (void *)0x0;
                pvStack_70 = (void *)0x0;
                local_68 = 0;
                IsSegmentConflicted(UTL_geoid_const&,std::shared_ptr<ATCControllerCab_const>,ATCFlightSegment_const*)
                ::$_32::operator()((__32 *)&local_a0,(ATCNetwork_halfedge *)&local_108);
                std::
                __set_difference<std::__less<runway_spec_t,runway_spec_t>&,std::__tree_const_iterator<runway_spec_t,std::__tree_node<runway_spec_t,void*>*,long>,std::__tree_const_iterator<runway_spec_t,std::__tree_node<runway_spec_t,void*>*,long>,std::back_insert_iterator<std::vector<runway_spec_t,std::allocator<runway_spec_t>>>>
                          (local_a0,local_98,local_d8,&p_Stack_d0,&local_78,local_38);
                bVar6 = bVar5;
                if (local_78 != pvStack_70) {
                  bVar6 = false;
                }
                std::__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>>::
                destroy((__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>>
                         *)&local_a0,local_98[0]);
                if (local_78 != (void *)0x0) {
                  pvStack_70 = local_78;
                  operator_delete(local_78);
                }
                if (((*(long *)(piVar10 + 0x22) == 0) || (!bVar6)) ||
                   (piVar10 = *(int **)(*(long *)(piVar10 + 0x22) + 0x90), piVar10 == (int *)0x0))
                break;
              }
            }
            p_Var14 = local_b0;
            pfVar1 = (float *)(*(long *)(*(long *)(p_Var15 + 0x20) + 0x88) + 0x38);
            if (local_40 < *pfVar1 || local_40 == *pfVar1) {
              bVar5 = bVar6;
              if (local_3c < *(float *)(*(long *)(*(long *)(p_Var15 + 0x20) + 0x90) + 0x38)) {
                bVar5 = false;
              }
            }
            else {
              bVar5 = false;
            }
            p_Var11 = *(__tree_node **)(p_Var15 + 8);
            if (*(__tree_node **)(p_Var15 + 8) == (__tree_node *)0x0) {
              p_Var9 = *(__tree_node **)(p_Var15 + 0x10);
              if (*(__tree_node **)p_Var9 != p_Var15) {
                do {
                  p_Var15 = *(__tree_node **)(p_Var15 + 0x10);
                  p_Var9 = *(__tree_node **)(p_Var15 + 0x10);
                } while (*(__tree_node **)p_Var9 != p_Var15);
              }
            }
            else {
              do {
                p_Var9 = p_Var11;
                p_Var11 = *(__tree_node **)p_Var9;
              } while (*(__tree_node **)p_Var9 != (__tree_node *)0x0);
            }
            p_Var15 = p_Var9;
          } while (bVar5);
          std::__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>>::destroy
                    ((__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>> *
                     )&local_d8,p_Stack_d0);
          lVar16 = local_80;
        }
LAB_001f77d0:
        p_Var15 = *(__tree_node **)(p_Var14 + 8);
        if (*(__tree_node **)(p_Var14 + 8) == (__tree_node *)0x0) {
          p_Var11 = *(__tree_node **)(p_Var14 + 0x10);
          if (*(__tree_node **)p_Var11 != p_Var14) {
            do {
              p_Var14 = *(__tree_node **)(p_Var14 + 0x10);
              p_Var11 = *(__tree_node **)(p_Var14 + 0x10);
            } while (*(__tree_node **)p_Var11 != p_Var14);
          }
        }
        else {
          do {
            p_Var11 = p_Var15;
            p_Var15 = *(__tree_node **)p_Var11;
          } while (*(__tree_node **)p_Var11 != (__tree_node *)0x0);
        }
        p_Var14 = p_Var11;
      } while (p_Var11 != (__tree_node *)&local_58);
    }
    bVar6 = true;
    bVar5 = true;
joined_r0x001f784c:
    if (local_48 != (long *)0x0) {
      LOCK();
      plVar2 = local_48 + 1;
      lVar3 = *plVar2;
      *plVar2 = *plVar2 + -1;
      UNLOCK();
      bVar5 = bVar6;
      if (lVar3 == 0) {
        (**(code **)(*local_48 + 0x10))(local_48);
        std::__shared_weak_count::__release_weak();
      }
    }
    std::__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>>::destroy
              ((__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>> *)
               &local_f0,local_e8);
    std::
    __tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
    ::destroy((__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
               *)&local_60,local_58);
    if (!bVar5) {
      return 1;
    }
  }
  return 0;
}


// 001f79d0  ATCFlightRouteUtils::IsSegmentConflicted(UTL_geoid_const&,std::shared_ptr<ATCControllerCab_const>,ATCFlightSegment_const*)::$_32::operator()

/* ATCFlightRouteUtils::IsSegmentConflicted(UTL_geoid const&, std::shared_ptr<ATCControllerCab
   const>, ATCFlightSegment const*)::$_32::TEMPNAMEPLACEHOLDERVALUE(ATCNetwork_halfedge const*)
   const */

void __thiscall
ATCFlightRouteUtils::
IsSegmentConflicted(UTL_geoid_const&,std::shared_ptr<ATCControllerCab_const>,ATCFlightSegment_const*)
::$_32::operator()(__32 *this,ATCNetwork_halfedge *param_1)

{
  __32 *p_Var1;
  ATCNetwork_halfedge AVar2;
  long *plVar3;
  ulong uVar4;
  long lVar5;
  ATCNetwork_halfedge *pAVar6;
  ATCNetwork_halfedge *pAVar7;
  __32 *p_Var8;
  char cVar9;
  __tree_node_base *p_Var10;
  ATCNetwork_halfedge *pAVar11;
  ATCNetwork_halfedge *in_RDX;
  long *plVar12;
  long *plVar13;
  long *plVar14;
  __32 *p_Var15;
  __32 *p_Var16;
  
  p_Var1 = this + 8;
  *(undefined8 *)(this + 8) = 0;
  *(undefined8 *)(this + 0x10) = 0;
  *(__32 **)this = p_Var1;
  cVar9 = ATCControllerCab::IsActiveZone
                    (*(ATCControllerCab **)(param_1 + 8),in_RDX,(runway_spec_t *)0x0);
  if (cVar9 != '\0') {
    pAVar11 = *(ATCNetwork_halfedge **)(in_RDX + 0x60);
    while (pAVar7 = pAVar11, pAVar7 != in_RDX + 0x68) {
      plVar3 = *(long **)(*(long *)param_1 + 8);
      if (plVar3 == (long *)0x0) {
LAB_001f7b00:
        pAVar6 = *(ATCNetwork_halfedge **)(pAVar7 + 8);
        if (*(ATCNetwork_halfedge **)(pAVar7 + 8) == (ATCNetwork_halfedge *)0x0) goto LAB_001f7b90;
LAB_001f7b10:
        do {
          pAVar11 = pAVar6;
          pAVar6 = *(ATCNetwork_halfedge **)pAVar11;
        } while (pAVar6 != (ATCNetwork_halfedge *)0x0);
      }
      else {
        uVar4 = *(ulong *)(pAVar7 + 0x20);
        AVar2 = pAVar7[0x28];
        plVar12 = (long *)(*(long *)param_1 + 8);
        plVar14 = plVar12;
        do {
          while ((plVar13 = plVar3, (ulong)plVar13[4] < uVar4 ||
                 ((plVar13[4] == uVar4 &&
                  ((byte)*(ATCNetwork_halfedge *)(plVar13 + 5) < (byte)AVar2))))) {
            plVar3 = (long *)plVar13[1];
            if ((long *)plVar13[1] == (long *)0x0) goto LAB_001f7a94;
          }
          plVar3 = (long *)*plVar13;
          plVar14 = plVar13;
        } while ((long *)*plVar13 != (long *)0x0);
LAB_001f7a94:
        if (((plVar14 == plVar12) || (uVar4 < (ulong)plVar14[4])) ||
           ((uVar4 <= (ulong)plVar14[4] &&
            ((byte)AVar2 < (byte)*(ATCNetwork_halfedge *)(plVar14 + 5))))) goto LAB_001f7b00;
        p_Var8 = *(__32 **)p_Var1;
        p_Var16 = p_Var1;
        if (*(__32 **)p_Var1 == (__32 *)0x0) {
          lVar5 = *(long *)p_Var1;
          p_Var15 = p_Var1;
        }
        else {
          do {
            while (p_Var15 = p_Var8, uVar4 < *(ulong *)(p_Var15 + 0x20)) {
LAB_001f7ac0:
              p_Var8 = *(__32 **)p_Var15;
              p_Var16 = p_Var15;
              if (*(__32 **)p_Var15 == (__32 *)0x0) {
                lVar5 = *(long *)p_Var15;
                goto joined_r0x001f7bcd;
              }
            }
            if (uVar4 == *(ulong *)(p_Var15 + 0x20)) {
              if ((byte)AVar2 < (byte)*(ATCNetwork_halfedge *)(p_Var15 + 0x28)) goto LAB_001f7ac0;
              if ((byte)AVar2 <= (byte)*(ATCNetwork_halfedge *)(p_Var15 + 0x28)) break;
            }
            p_Var16 = p_Var15 + 8;
            p_Var8 = *(__32 **)(p_Var15 + 8);
          } while (*(__32 **)(p_Var15 + 8) != (__32 *)0x0);
          lVar5 = *(long *)p_Var16;
        }
joined_r0x001f7bcd:
        if (lVar5 != 0) goto LAB_001f7b00;
        p_Var10 = operator_new(0x30);
        lVar5 = *(long *)(pAVar7 + 0x28);
        *(long *)(p_Var10 + 0x20) = *(long *)(pAVar7 + 0x20);
        *(long *)(p_Var10 + 0x28) = lVar5;
        *(undefined8 *)p_Var10 = 0;
        *(undefined8 *)(p_Var10 + 8) = 0;
        *(__32 **)(p_Var10 + 0x10) = p_Var15;
        *(__tree_node_base **)p_Var16 = p_Var10;
        if (**(long **)this != 0) {
          *(long *)this = **(long **)this;
          p_Var10 = *(__tree_node_base **)p_Var16;
        }
        std::__tree_balance_after_insert<std::__tree_node_base<void*>*>
                  (*(__tree_node_base **)(this + 8),p_Var10);
        *(long *)(this + 0x10) = *(long *)(this + 0x10) + 1;
        pAVar6 = *(ATCNetwork_halfedge **)(pAVar7 + 8);
        if (*(ATCNetwork_halfedge **)(pAVar7 + 8) != (ATCNetwork_halfedge *)0x0) goto LAB_001f7b10;
LAB_001f7b90:
        pAVar11 = *(ATCNetwork_halfedge **)(pAVar7 + 0x10);
        if (*(ATCNetwork_halfedge **)*(ATCNetwork_halfedge **)(pAVar7 + 0x10) != pAVar7) {
          do {
            pAVar7 = *(ATCNetwork_halfedge **)(pAVar7 + 0x10);
            pAVar11 = *(ATCNetwork_halfedge **)(pAVar7 + 0x10);
          } while (*(ATCNetwork_halfedge **)*(ATCNetwork_halfedge **)(pAVar7 + 0x10) != pAVar7);
        }
      }
    }
  }
  return;
}


// 001f7c10  ATCFlightRouteUtils::FindSafeSplit

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* ATCFlightRouteUtils::FindSafeSplit(ATCAircraft const*, units::value<float,
   units::scale<units::units::m, 1, 1852> >&, GeoPoint2D&, ATCFlightSegment*&) */

undefined8
ATCFlightRouteUtils::FindSafeSplit
          (ATCAircraft *param_1,value *param_2,GeoPoint2D *param_3,ATCFlightSegment **param_4)

{
  long lVar1;
  ATCFlightSegment *pAVar2;
  long lVar3;
  char cVar4;
  UTL_geoid *pUVar5;
  undefined8 uVar6;
  float fVar7;
  float fVar8;
  ATCFlightRoute *pAVar9;
  
  uVar6 = *(undefined8 *)(param_1 + 0x60);
                    /* WARNING: Load size is inaccurate */
  pAVar9._0_4_ = *(ATCFlightRoute **)param_2;
  do {
    cVar4 = ATCFlightRoute::FindGeoPtByDistFromEnd(pAVar9._0_4_,uVar6,param_3,param_4);
    if (cVar4 == '\0') {
      return 0;
    }
    lVar1 = *(long *)(*param_4 + 0x90);
    pUVar5 = (UTL_geoid *)REN_geoid::instance();
    fVar7 = (float)ATCGeomDistBetweenLonLatPts(pUVar5,param_3,(GeoPoint2D *)(lVar1 + 0x40));
    cVar4 = '\0';
    if (fVar7 != DAT_02536f38) {
      cVar4 = -0x7f;
    }
    if (DAT_02536f38 < fVar7) {
      cVar4 = '\x01';
    }
    if (fVar7 < DAT_02536f38) {
      cVar4 = -1;
    }
    pAVar2 = *param_4;
    if ((cVar4 == -0x7f) || (-1 < cVar4)) {
      lVar1 = *(long *)(pAVar2 + 0x88);
      pUVar5 = (UTL_geoid *)REN_geoid::instance();
      fVar7 = (float)ATCGeomDistBetweenLonLatPts(pUVar5,param_3,(GeoPoint2D *)(lVar1 + 0x40));
      cVar4 = '\0';
      if (fVar7 != DAT_02536f38) {
        cVar4 = -0x7f;
      }
      if (DAT_02536f38 < fVar7) {
        cVar4 = '\x01';
      }
      if (fVar7 < DAT_02536f38) {
        cVar4 = -1;
      }
      if (cVar4 == -0x7f) {
        return 1;
      }
      if (-1 < cVar4) {
        return 1;
      }
      lVar1 = *(long *)(*param_4 + 0x88);
      lVar3 = *(long *)(*param_4 + 0x90);
      pUVar5 = (UTL_geoid *)REN_geoid::instance();
      fVar8 = (float)ATCGeomDistBetweenLonLatPts
                               (pUVar5,(GeoPoint2D *)(lVar3 + 0x40),(GeoPoint2D *)(lVar1 + 0x40));
      fVar7 = DAT_02536f38;
      if (_DAT_0253ae20 < fVar8) goto LAB_001f7dc1;
    }
    else {
      lVar1 = *(long *)(pAVar2 + 0x88);
      lVar3 = *(long *)(pAVar2 + 0x90);
      pUVar5 = (UTL_geoid *)REN_geoid::instance();
      fVar8 = (float)ATCGeomDistBetweenLonLatPts
                               (pUVar5,(GeoPoint2D *)(lVar3 + 0x40),(GeoPoint2D *)(lVar1 + 0x40));
      fVar7 = DAT_0253ae24;
      if (_DAT_0253ae20 < fVar8) {
LAB_001f7dc1:
        *(float *)param_2 = fVar7 + *(float *)param_2;
        uVar6 = ATCFlightRoute::FindGeoPtByDistFromEnd
                          (*(ATCFlightRoute **)(param_1 + 0x60),param_3,param_4);
        return uVar6;
      }
    }
    pAVar9._0_4_ = (ATCFlightRoute *)(*(float *)param_2 + DAT_0253ae28);
                    /* WARNING: Store size is inaccurate */
    *(ATCFlightRoute **)param_2 = pAVar9._0_4_;
    uVar6 = *(undefined8 *)(param_1 + 0x60);
  } while( true );
}


// 00217c40  AIRNAV5::Navigation::FlightRoute::~FlightRoute

/* WARNING: Type propagation algorithm not settling */
/* AIRNAV5::Navigation::FlightRoute::~FlightRoute() */

void __thiscall AIRNAV5::Navigation::FlightRoute::~FlightRoute(FlightRoute *this)

{
  FlightRoute FVar1;
  long *plVar2;
  undefined8 *puVar3;
  void *pvVar4;
  void *pvVar5;
  undefined8 *puVar6;
  long *plVar7;
  undefined8 *puVar8;
  void *pvVar9;
  
  *(undefined ***)this = &PTR__FlightRoute_02b7f248;
  *(undefined ***)(this + 0x20a0) = &PTR__Waypoint_02b7f1d8;
  if (((byte)this[0x20f8] & 1) == 0) {
    *(undefined ***)(this + 0x2008) = &PTR__Waypoint_02b7f1d8;
    FVar1 = this[0x2060];
  }
  else {
    operator_delete(*(void **)(this + 0x2108));
    *(undefined ***)(this + 0x2008) = &PTR__Waypoint_02b7f1d8;
    FVar1 = this[0x2060];
  }
  if (((byte)FVar1 & 1) == 0) {
    plVar2 = *(long **)(this + 0x1ff0);
    *(undefined8 *)(this + 0x1ff0) = 0;
  }
  else {
    operator_delete(*(void **)(this + 0x2070));
    plVar2 = *(long **)(this + 0x1ff0);
    *(undefined8 *)(this + 0x1ff0) = 0;
  }
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  puVar3 = *(undefined8 **)(this + 0x1fd8);
  if (puVar3 != (undefined8 *)0x0) {
    puVar6 = *(undefined8 **)(this + 0x1fe0);
    puVar8 = puVar3;
    if (puVar6 != puVar3) {
      do {
        puVar6 = puVar6 + -0x68;
        (**(code **)*puVar6)(puVar6);
      } while (puVar6 != puVar3);
      puVar8 = *(undefined8 **)(this + 0x1fd8);
    }
    *(undefined8 **)(this + 0x1fe0) = puVar3;
    operator_delete(puVar8);
  }
  *(undefined ***)(this + 0x1c48) = &PTR__Leg_02b7f088;
  plVar2 = *(long **)(this + 0x1f70);
  *(undefined8 *)(this + 0x1f70) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  pvVar4 = *(void **)(this + 8000);
  if (pvVar4 != (void *)0x0) {
    *(void **)(this + 0x1f48) = pvVar4;
    operator_delete(pvVar4);
  }
  if (((byte)this[0x1ea0] & 1) != 0) {
    operator_delete(*(void **)(this + 0x1eb0));
  }
  plVar2 = *(long **)(this + 0x1e98);
  *(undefined8 *)(this + 0x1e98) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  if (((byte)this[0x1c28] & 1) == 0) {
    FVar1 = this[0x1c10];
  }
  else {
    operator_delete(*(void **)(this + 0x1c38));
    FVar1 = this[0x1c10];
  }
  if (((byte)FVar1 & 1) == 0) {
    pvVar4 = *(void **)(this + 0x1bf8);
  }
  else {
    operator_delete(*(void **)(this + 0x1c20));
    pvVar4 = *(void **)(this + 0x1bf8);
  }
  if (pvVar4 != (void *)0x0) {
    pvVar5 = *(void **)(this + 0x1c00);
    pvVar9 = pvVar4;
    if (*(void **)(this + 0x1c00) != pvVar4) {
      do {
        pvVar9 = (void *)((long)pvVar5 + -0x20);
        if ((*(byte *)((long)pvVar5 + -0x20) & 1) != 0) {
          operator_delete(*(void **)((long)pvVar5 + -0x10));
        }
        pvVar5 = pvVar9;
      } while (pvVar9 != pvVar4);
      pvVar9 = *(void **)(this + 0x1bf8);
    }
    *(void **)(this + 0x1c00) = pvVar4;
    operator_delete(pvVar9);
  }
  *(undefined ***)(this + 0x18b8) = &PTR__Leg_02b7f088;
  plVar2 = *(long **)(this + 0x1be0);
  *(undefined8 *)(this + 0x1be0) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  pvVar4 = *(void **)(this + 0x1bb0);
  if (pvVar4 != (void *)0x0) {
    *(void **)(this + 0x1bb8) = pvVar4;
    operator_delete(pvVar4);
  }
  if (((byte)this[0x1b10] & 1) != 0) {
    operator_delete(*(void **)(this + 0x1b20));
  }
  plVar2 = *(long **)(this + 0x1b08);
  *(undefined8 *)(this + 0x1b08) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  *(undefined ***)(this + 0x1578) = &PTR__Leg_02b7f088;
  plVar2 = *(long **)(this + 0x18a0);
  *(undefined8 *)(this + 0x18a0) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  pvVar4 = *(void **)(this + 0x1870);
  if (pvVar4 != (void *)0x0) {
    *(void **)(this + 0x1878) = pvVar4;
    operator_delete(pvVar4);
  }
  if (((byte)this[0x17d0] & 1) != 0) {
    operator_delete(*(void **)(this + 0x17e0));
  }
  plVar2 = *(long **)(this + 0x17c8);
  *(undefined8 *)(this + 0x17c8) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  *(undefined ***)(this + 0x1238) = &PTR__Leg_02b7f088;
  plVar2 = *(long **)(this + 0x1560);
  *(undefined8 *)(this + 0x1560) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  pvVar4 = *(void **)(this + 0x1530);
  if (pvVar4 != (void *)0x0) {
    *(void **)(this + 0x1538) = pvVar4;
    operator_delete(pvVar4);
  }
  if (((byte)this[0x1490] & 1) != 0) {
    operator_delete(*(void **)(this + 0x14a0));
  }
  plVar2 = *(long **)(this + 0x1488);
  *(undefined8 *)(this + 0x1488) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  *(undefined ***)(this + 0xef8) = &PTR__Leg_02b7f088;
  plVar2 = *(long **)(this + 0x1220);
  *(undefined8 *)(this + 0x1220) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  pvVar4 = *(void **)(this + 0x11f0);
  if (pvVar4 != (void *)0x0) {
    *(void **)(this + 0x11f8) = pvVar4;
    operator_delete(pvVar4);
  }
  if (((byte)this[0x1150] & 1) != 0) {
    operator_delete(*(void **)(this + 0x1160));
  }
  plVar2 = *(long **)(this + 0x1148);
  *(undefined8 *)(this + 0x1148) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  *(undefined ***)(this + 3000) = &PTR__Leg_02b7f088;
  plVar2 = *(long **)(this + 0xee0);
  *(undefined8 *)(this + 0xee0) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  pvVar4 = *(void **)(this + 0xeb0);
  if (pvVar4 != (void *)0x0) {
    *(void **)(this + 0xeb8) = pvVar4;
    operator_delete(pvVar4);
  }
  if (((byte)this[0xe10] & 1) != 0) {
    operator_delete(*(void **)(this + 0xe20));
  }
  plVar2 = *(long **)(this + 0xe08);
  *(undefined8 *)(this + 0xe08) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  *(undefined ***)(this + 0x878) = &PTR__Leg_02b7f088;
  plVar2 = *(long **)(this + 0xba0);
  *(undefined8 *)(this + 0xba0) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  pvVar4 = *(void **)(this + 0xb70);
  if (pvVar4 != (void *)0x0) {
    *(void **)(this + 0xb78) = pvVar4;
    operator_delete(pvVar4);
  }
  if (((byte)this[0xad0] & 1) != 0) {
    operator_delete(*(void **)(this + 0xae0));
  }
  plVar2 = *(long **)(this + 0xac8);
  *(undefined8 *)(this + 0xac8) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  *(undefined ***)(this + 0x538) = &PTR__Leg_02b7f088;
  plVar2 = *(long **)(this + 0x860);
  *(undefined8 *)(this + 0x860) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  pvVar4 = *(void **)(this + 0x830);
  if (pvVar4 != (void *)0x0) {
    *(void **)(this + 0x838) = pvVar4;
    operator_delete(pvVar4);
  }
  if (((byte)this[0x790] & 1) != 0) {
    operator_delete(*(void **)(this + 0x7a0));
  }
  plVar2 = *(long **)(this + 0x788);
  *(undefined8 *)(this + 0x788) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  *(undefined ***)(this + 0x1f8) = &PTR__Leg_02b7f088;
  plVar2 = *(long **)(this + 0x520);
  *(undefined8 *)(this + 0x520) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  pvVar4 = *(void **)(this + 0x4f0);
  if (pvVar4 != (void *)0x0) {
    *(void **)(this + 0x4f8) = pvVar4;
    operator_delete(pvVar4);
  }
  if (((byte)this[0x450] & 1) != 0) {
    operator_delete(*(void **)(this + 0x460));
  }
  plVar2 = *(long **)(this + 0x448);
  *(undefined8 *)(this + 0x448) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  plVar2 = *(long **)(this + 0x110);
  *(undefined8 *)(this + 0x110) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  if (((byte)this[0xf8] & 1) == 0) {
    FVar1 = this[0xd8];
  }
  else {
    operator_delete(*(void **)(this + 0x108));
    FVar1 = this[0xd8];
  }
  if (((byte)FVar1 & 1) == 0) {
    FVar1 = this[0xc0];
  }
  else {
    operator_delete(*(void **)(this + 0xe8));
    FVar1 = this[0xc0];
  }
  if (((byte)FVar1 & 1) == 0) {
    FVar1 = this[0xa8];
  }
  else {
    operator_delete(*(void **)(this + 0xd0));
    FVar1 = this[0xa8];
  }
  if (((byte)FVar1 & 1) == 0) {
    FVar1 = this[0x90];
  }
  else {
    operator_delete(*(void **)(this + 0xb8));
    FVar1 = this[0x90];
  }
  if (((byte)FVar1 & 1) == 0) {
    FVar1 = this[0x78];
  }
  else {
    operator_delete(*(void **)(this + 0xa0));
    FVar1 = this[0x78];
  }
  if (((byte)FVar1 & 1) == 0) {
    FVar1 = this[0x60];
  }
  else {
    operator_delete(*(void **)(this + 0x88));
    FVar1 = this[0x60];
  }
  if (((byte)FVar1 & 1) == 0) {
    FVar1 = this[0x48];
  }
  else {
    operator_delete(*(void **)(this + 0x70));
    FVar1 = this[0x48];
  }
  if (((byte)FVar1 & 1) == 0) {
    FVar1 = this[0x30];
  }
  else {
    operator_delete(*(void **)(this + 0x58));
    FVar1 = this[0x30];
  }
  if (((byte)FVar1 & 1) == 0) {
    plVar2 = *(long **)(this + 0x28);
    *(undefined8 *)(this + 0x28) = 0;
  }
  else {
    operator_delete(*(void **)(this + 0x40));
    plVar2 = *(long **)(this + 0x28);
    *(undefined8 *)(this + 0x28) = 0;
  }
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  plVar2 = *(long **)(this + 0x20);
  *(undefined8 *)(this + 0x20) = 0;
  if (plVar2 != (long *)0x0) {
    (**(code **)(*plVar2 + 8))();
  }
  *(undefined ***)this = &PTR__Route_02b7f338;
  plVar7 = *(long **)(this + 8);
  plVar2 = *(long **)(this + 0x10);
  if (plVar7 != plVar2) {
    do {
      if ((long *)*plVar7 != (long *)0x0) {
        (**(code **)(*(long *)*plVar7 + 8))();
      }
      plVar7 = plVar7 + 1;
    } while (plVar7 != plVar2);
    plVar7 = *(long **)(this + 8);
  }
  if (plVar7 != (long *)0x0) {
    *(long **)(this + 0x10) = plVar7;
    operator_delete(plVar7);
    return;
  }
  return;
}


// 002250d0  ATCAircraftFlightPlan::~ATCAircraftFlightPlan

/* ATCAircraftFlightPlan::~ATCAircraftFlightPlan() */

void __thiscall ATCAircraftFlightPlan::~ATCAircraftFlightPlan(ATCAircraftFlightPlan *this)

{
  ATCAircraftFlightPlan AVar1;
  
  if (((byte)this[0x88] & 1) == 0) {
    AVar1 = this[0x70];
  }
  else {
    operator_delete(*(void **)(this + 0x98));
    AVar1 = this[0x70];
  }
  if (((byte)AVar1 & 1) == 0) {
    AVar1 = this[0x50];
  }
  else {
    operator_delete(*(void **)(this + 0x80));
    AVar1 = this[0x50];
  }
  if (((byte)AVar1 & 1) == 0) {
    AVar1 = this[0x38];
  }
  else {
    operator_delete(*(void **)(this + 0x60));
    AVar1 = this[0x38];
  }
  if (((byte)AVar1 & 1) == 0) {
    AVar1 = this[0x20];
  }
  else {
    operator_delete(*(void **)(this + 0x48));
    AVar1 = this[0x20];
  }
  if (((byte)AVar1 & 1) == 0) {
    AVar1 = this[8];
  }
  else {
    operator_delete(*(void **)(this + 0x30));
    AVar1 = this[8];
  }
  if (((byte)AVar1 & 1) != 0) {
    operator_delete(*(void **)(this + 0x18));
    return;
  }
  return;
}


// 00225170  std::__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>::__emplace_hint_unique_key_args<ATCAircraft_const*,std::pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>const&>

/* std::pair<std::__tree_iterator<std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment
   const*, std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > >,
   std::__tree_node<std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment const*,
   std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > >, void*>*, long>,
   bool> std::__tree<std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment const*,
   std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > >,
   std::__map_value_compare<ATCAircraft const*, std::__value_type<ATCAircraft const*,
   std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > >, std::less<ATCAircraft const*>, true>,
   std::allocator<std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment const*,
   std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > > >
   >::__emplace_hint_unique_key_args<ATCAircraft const*, std::pair<ATCAircraft const* const,
   std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > >
   const&>(std::__tree_const_iterator<std::__value_type<ATCAircraft const*,
   std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > >, std::__tree_node<std::__value_type<ATCAircraft
   const*, std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > >, void*>*, long>, ATCAircraft const* const&,
   std::pair<ATCAircraft const* const, std::set<ATCFlightSegment const*, std::less<ATCFlightSegment
   const*>, std::allocator<ATCFlightSegment const*> > > const&) */

undefined1  [16] __thiscall
std::
__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
::
__emplace_hint_unique_key_args<ATCAircraft_const*,std::pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>const&>
          (__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
           *this,undefined8 param_2,undefined8 param_3,pair *param_4)

{
  __tree_node_base **pp_Var1;
  __tree_node_base *p_Var2;
  undefined8 extraout_RDX;
  undefined8 uVar3;
  __tree_node_base *p_Var4;
  undefined1 auVar5 [16];
  undefined1 local_38 [8];
  undefined8 local_30;
  
  pp_Var1 = __find_equal<ATCAircraft_const*>(this,param_2,&local_30,local_38,param_3);
  p_Var2 = *pp_Var1;
  if (p_Var2 == (__tree_node_base *)0x0) {
    p_Var2 = operator_new(0x40);
    pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
    ::pair((pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
            *)(p_Var2 + 0x20),param_4);
    *(undefined8 *)p_Var2 = 0;
    *(undefined8 *)(p_Var2 + 8) = 0;
    *(undefined8 *)(p_Var2 + 0x10) = local_30;
    *pp_Var1 = p_Var2;
    p_Var4 = p_Var2;
    if (**(long **)this != 0) {
      *(long *)this = **(long **)this;
      p_Var4 = *pp_Var1;
    }
    __tree_balance_after_insert<std::__tree_node_base<void*>*>
              (*(__tree_node_base **)(this + 8),p_Var4);
    *(long *)(this + 0x10) = *(long *)(this + 0x10) + 1;
    uVar3 = CONCAT71((int7)((ulong)extraout_RDX >> 8),1);
  }
  else {
    uVar3 = 0;
  }
  auVar5._8_8_ = uVar3;
  auVar5._0_8_ = p_Var2;
  return auVar5;
}


// 00225220  std::__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>::__find_equal<ATCAircraft_const*>

/* std::__tree_node_base<void*>*& std::__tree<std::__value_type<ATCAircraft const*,
   std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > >, std::__map_value_compare<ATCAircraft const*,
   std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment const*,
   std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > >,
   std::less<ATCAircraft const*>, true>, std::allocator<std::__value_type<ATCAircraft const*,
   std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > > > >::__find_equal<ATCAircraft
   const*>(std::__tree_const_iterator<std::__value_type<ATCAircraft const*,
   std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > >, std::__tree_node<std::__value_type<ATCAircraft
   const*, std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > >, void*>*, long>,
   std::__tree_end_node<std::__tree_node_base<void*>*>*&, std::__tree_node_base<void*>*&,
   ATCAircraft const* const&) */

__tree_node_base ** __thiscall
std::
__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
::__find_equal<ATCAircraft_const*>
          (__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
           *this,__tree_node_base *param_2,long *param_3,__tree_node_base **param_4,ulong *param_5)

{
  long lVar1;
  __tree_node_base *p_Var2;
  __tree_node_base *p_Var3;
  __tree_node_base *p_Var4;
  __tree_node_base *p_Var5;
  ulong uVar6;
  
  p_Var3 = (__tree_node_base *)(this + 8);
  if (p_Var3 != param_2) {
    uVar6 = *param_5;
    if (*(ulong *)(param_2 + 0x20) <= uVar6) {
      if (uVar6 <= *(ulong *)(param_2 + 0x20)) {
        *param_3 = (long)param_2;
        *param_4 = param_2;
        return param_4;
      }
      p_Var2 = *(__tree_node_base **)(param_2 + 8);
      p_Var4 = p_Var2;
      if (p_Var2 == (__tree_node_base *)0x0) {
        p_Var5 = *(__tree_node_base **)(param_2 + 0x10);
        p_Var4 = param_2;
        if (*(__tree_node_base **)p_Var5 != param_2) {
          do {
            p_Var4 = *(__tree_node_base **)(p_Var4 + 0x10);
            p_Var5 = *(__tree_node_base **)(p_Var4 + 0x10);
          } while (*(__tree_node_base **)p_Var5 != p_Var4);
        }
      }
      else {
        do {
          p_Var5 = p_Var4;
          p_Var4 = *(__tree_node_base **)p_Var5;
        } while (*(__tree_node_base **)p_Var5 != (__tree_node_base *)0x0);
      }
      if ((p_Var5 == p_Var3) || (uVar6 < *(ulong *)(p_Var5 + 0x20))) {
        if (p_Var2 == (__tree_node_base *)0x0) {
          *param_3 = (long)param_2;
          return (__tree_node_base **)(param_2 + 8);
        }
        *param_3 = (long)p_Var5;
        return (__tree_node_base **)p_Var5;
      }
      p_Var2 = *(__tree_node_base **)p_Var3;
      if (*(__tree_node_base **)p_Var3 != (__tree_node_base *)0x0) {
        do {
          while (p_Var4 = p_Var2, uVar6 < *(ulong *)(p_Var4 + 0x20)) {
            p_Var3 = p_Var4;
            p_Var2 = *(__tree_node_base **)p_Var4;
            if (*(__tree_node_base **)p_Var4 == (__tree_node_base *)0x0) {
              *param_3 = (long)p_Var4;
              return (__tree_node_base **)p_Var4;
            }
          }
          if (uVar6 <= *(ulong *)(p_Var4 + 0x20)) break;
          p_Var3 = p_Var4 + 8;
          p_Var2 = *(__tree_node_base **)(p_Var4 + 8);
        } while (*(__tree_node_base **)(p_Var4 + 8) != (__tree_node_base *)0x0);
        *param_3 = (long)p_Var4;
        return (__tree_node_base **)p_Var3;
      }
      goto LAB_00225370;
    }
  }
  p_Var4 = *(__tree_node_base **)param_2;
  p_Var2 = param_2;
  if (*(__tree_node_base **)this != param_2) {
    p_Var5 = p_Var4;
    if (p_Var4 == (__tree_node_base *)0x0) {
      p_Var2 = param_2 + 0x10;
      if ((__tree_node_base *)**(undefined8 **)(param_2 + 0x10) == param_2) {
        do {
          lVar1 = *(long *)p_Var2;
          p_Var2 = (__tree_node_base *)(lVar1 + 0x10);
        } while (**(long **)(lVar1 + 0x10) == lVar1);
      }
      p_Var2 = *(__tree_node_base **)p_Var2;
      uVar6 = *param_5;
      if (uVar6 <= *(ulong *)(p_Var2 + 0x20)) goto LAB_002252cc;
    }
    else {
      do {
        p_Var2 = p_Var5;
        p_Var5 = *(__tree_node_base **)(p_Var2 + 8);
      } while (*(__tree_node_base **)(p_Var2 + 8) != (__tree_node_base *)0x0);
      uVar6 = *param_5;
      if (uVar6 <= *(ulong *)(p_Var2 + 0x20)) {
LAB_002252cc:
        if (*(__tree_node_base **)p_Var3 == (__tree_node_base *)0x0) {
LAB_00225370:
          *param_3 = (long)p_Var3;
          return (__tree_node_base **)p_Var3;
        }
        p_Var2 = (__tree_node_base *)(this + 8);
        p_Var3 = *(__tree_node_base **)p_Var3;
LAB_002252fe:
        do {
          param_2 = p_Var3;
          if (*(ulong *)(param_2 + 0x20) <= uVar6) {
            if (*(ulong *)(param_2 + 0x20) < uVar6) {
              p_Var2 = param_2 + 8;
              p_Var3 = *(__tree_node_base **)(param_2 + 8);
              if (*(__tree_node_base **)(param_2 + 8) != (__tree_node_base *)0x0) goto LAB_002252fe;
            }
            *param_3 = (long)param_2;
            return (__tree_node_base **)p_Var2;
          }
          p_Var2 = param_2;
          p_Var3 = *(__tree_node_base **)param_2;
        } while (*(__tree_node_base **)param_2 != (__tree_node_base *)0x0);
        goto LAB_00225318;
      }
    }
  }
  if (p_Var4 != (__tree_node_base *)0x0) {
    *param_3 = (long)p_Var2;
    return (__tree_node_base **)(p_Var2 + 8);
  }
LAB_00225318:
  *param_3 = (long)param_2;
  return (__tree_node_base **)param_2;
}


// 002253c0  std::pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>::pair

/* WARNING: Removing unreachable block (ram,0x00225423) */
/* std::pair<ATCAircraft const* const, std::set<ATCFlightSegment const*, std::less<ATCFlightSegment
   const*>, std::allocator<ATCFlightSegment const*> > >::pair(std::pair<ATCAircraft const* const,
   std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > > const&) */

void __thiscall
std::
pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
::pair(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
       *this,pair *param_1)

{
  pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
  *ppVar1;
  pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
  *ppVar2;
  long lVar3;
  long *plVar4;
  pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
  *ppVar5;
  __tree_node_base *p_Var6;
  long *plVar7;
  pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
  *ppVar8;
  ulong uVar9;
  pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
  *ppVar10;
  pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
  *ppVar11;
  long *plVar12;
  pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
  *ppVar13;
  
  *(undefined8 *)this = *(undefined8 *)param_1;
  ppVar1 = this + 0x10;
  *(undefined8 *)(this + 0x10) = 0;
  *(undefined8 *)(this + 0x18) = 0;
  *(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
    **)(this + 8) = ppVar1;
  plVar7 = *(long **)(param_1 + 8);
  if (plVar7 == (long *)(param_1 + 0x10)) {
    return;
  }
  ppVar2 = this + 8;
  ppVar5 = (pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
            *)0x0;
  ppVar10 = ppVar1;
LAB_0022545a:
  do {
    ppVar11 = ppVar10;
    plVar12 = plVar7;
    ppVar13 = ppVar10 + 8;
    if (ppVar5 == (pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
                   *)0x0) {
      ppVar11 = ppVar1;
      ppVar13 = ppVar1;
    }
LAB_00225469:
    if (*(long *)ppVar13 == 0) {
      p_Var6 = operator_new(0x28);
      *(long *)(p_Var6 + 0x20) = plVar12[4];
      *(undefined8 *)p_Var6 = 0;
      *(undefined8 *)(p_Var6 + 8) = 0;
      *(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
        **)(p_Var6 + 0x10) = ppVar11;
      *(__tree_node_base **)ppVar13 = p_Var6;
      if (**(long **)ppVar2 != 0) {
        *(long *)ppVar2 = **(long **)ppVar2;
        p_Var6 = *(__tree_node_base **)ppVar13;
      }
      __tree_balance_after_insert<std::__tree_node_base<void*>*>
                (*(__tree_node_base **)(this + 0x10),p_Var6);
      *(long *)(this + 0x18) = *(long *)(this + 0x18) + 1;
      plVar4 = (long *)plVar12[1];
      if ((long *)plVar12[1] == (long *)0x0) goto LAB_00225500;
LAB_002254e0:
      do {
        plVar7 = plVar4;
        plVar4 = (long *)*plVar7;
      } while ((long *)*plVar7 != (long *)0x0);
    }
    else {
      plVar4 = (long *)plVar12[1];
      if ((long *)plVar12[1] != (long *)0x0) goto LAB_002254e0;
LAB_00225500:
      plVar7 = (long *)plVar12[2];
      if ((long *)*plVar7 != plVar12) {
        do {
          plVar12 = (long *)plVar12[2];
          plVar7 = (long *)plVar12[2];
        } while ((long *)*plVar7 != plVar12);
      }
    }
    if (plVar7 == (long *)(param_1 + 0x10)) {
      return;
    }
    ppVar5 = *(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
               **)ppVar1;
    ppVar10 = ppVar1;
  } while (*(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
             **)ppVar2 == ppVar1);
  ppVar13 = ppVar5;
  if (ppVar5 == (pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
                 *)0x0) {
    ppVar8 = this + 0x20;
    if ((pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
         *)**(undefined8 **)(this + 0x20) == ppVar1) {
      do {
        lVar3 = *(long *)ppVar8;
        ppVar8 = (pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
                  *)(lVar3 + 0x10);
      } while (**(long **)(lVar3 + 0x10) == lVar3);
    }
    uVar9 = plVar7[4];
    ppVar10 = *(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
                **)ppVar8;
    ppVar13 = ppVar1;
    ppVar11 = ppVar1;
    if (*(ulong *)(*(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
                     **)ppVar8 + 0x20) < uVar9) goto LAB_0022545a;
  }
  else {
    do {
      ppVar10 = ppVar13;
      ppVar13 = *(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
                  **)(ppVar10 + 8);
    } while (*(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
               **)(ppVar10 + 8) !=
             (pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
              *)0x0);
    uVar9 = plVar7[4];
    ppVar13 = ppVar1;
    ppVar11 = ppVar1;
    if (*(ulong *)(ppVar10 + 0x20) < uVar9) goto LAB_0022545a;
  }
  while (plVar12 = plVar7,
        ppVar5 != (pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
                   *)0x0) {
    while (ppVar11 = ppVar5, uVar9 < *(ulong *)(ppVar11 + 0x20)) {
      ppVar5 = *(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
                 **)ppVar11;
      ppVar13 = ppVar11;
      if (*(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
            **)ppVar11 ==
          (pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
           *)0x0) goto LAB_00225469;
    }
    if (uVar9 <= *(ulong *)(ppVar11 + 0x20)) break;
    ppVar5 = *(pair<ATCAircraft_const*const,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>
               **)(ppVar11 + 8);
    ppVar13 = ppVar11 + 8;
  }
  goto LAB_00225469;
}


// 00225620  std::__tree<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>::destroy

/* std::__tree<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> >::destroy(std::__tree_node<ATCFlightSegment const*,
   void*>*) */

void __thiscall
std::
__tree<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>
::destroy(__tree<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>
          *this,__tree_node *param_1)

{
  if (param_1 != (__tree_node *)0x0) {
    destroy(this,*(__tree_node **)param_1);
    destroy(this,*(__tree_node **)(param_1 + 8));
    operator_delete(param_1);
    return;
  }
  return;
}


// 00225660  std::__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>::destroy

/* std::__tree<std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment const*,
   std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > >,
   std::__map_value_compare<ATCAircraft const*, std::__value_type<ATCAircraft const*,
   std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > >, std::less<ATCAircraft const*>, true>,
   std::allocator<std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment const*,
   std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > > >
   >::destroy(std::__tree_node<std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment
   const*, std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > >, void*>*)
    */

void __thiscall
std::
__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
::destroy(__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
          *this,__tree_node *param_1)

{
  if (param_1 != (__tree_node *)0x0) {
    destroy(this,*(__tree_node **)param_1);
    destroy(this,*(__tree_node **)(param_1 + 8));
    __tree<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>
    ::destroy((__tree<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>
               *)(param_1 + 0x28),*(__tree_node **)(param_1 + 0x30));
    operator_delete(param_1);
    return;
  }
  return;
}


// 00236510  std::__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>::__erase_unique<ATCAircraft_const*>

/* unsigned long std::__tree<std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment const*,
   std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > >,
   std::__map_value_compare<ATCAircraft const*, std::__value_type<ATCAircraft const*,
   std::set<ATCFlightSegment const*, std::less<ATCFlightSegment const*>,
   std::allocator<ATCFlightSegment const*> > >, std::less<ATCAircraft const*>, true>,
   std::allocator<std::__value_type<ATCAircraft const*, std::set<ATCFlightSegment const*,
   std::less<ATCFlightSegment const*>, std::allocator<ATCFlightSegment const*> > > >
   >::__erase_unique<ATCAircraft const*>(ATCAircraft const* const&) */

ulong __thiscall
std::
__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
::__erase_unique<ATCAircraft_const*>
          (__tree<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::__map_value_compare<ATCAircraft_const*,std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>,std::less<ATCAircraft_const*>,true>,std::allocator<std::__value_type<ATCAircraft_const*,std::set<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>>>>
           *this,ATCAircraft **param_1)

{
  __tree_node_base *p_Var1;
  ATCAircraft *pAVar2;
  long *plVar3;
  long *plVar4;
  __tree_node_base *p_Var5;
  __tree_node_base *p_Var6;
  
  p_Var1 = *(__tree_node_base **)(this + 8);
  if (p_Var1 != (__tree_node_base *)0x0) {
    pAVar2 = *param_1;
    p_Var5 = (__tree_node_base *)(this + 8);
    p_Var6 = p_Var1;
    do {
      if (*(ATCAircraft **)(p_Var6 + 0x20) >= pAVar2) {
        p_Var5 = p_Var6;
      }
      p_Var6 = *(__tree_node_base **)
                (p_Var6 + (ulong)(*(ATCAircraft **)(p_Var6 + 0x20) < pAVar2) * 8);
    } while (p_Var6 != (__tree_node_base *)0x0);
    if ((p_Var5 != (__tree_node_base *)(this + 8)) && (*(ATCAircraft **)(p_Var5 + 0x20) <= pAVar2))
    {
      plVar3 = *(long **)(p_Var5 + 8);
      if (*(long **)(p_Var5 + 8) == (long *)0x0) {
        plVar4 = *(long **)(p_Var5 + 0x10);
        p_Var6 = p_Var5;
        if ((__tree_node_base *)*plVar4 != p_Var5) {
          do {
            p_Var6 = *(__tree_node_base **)(p_Var6 + 0x10);
            plVar4 = *(long **)(p_Var6 + 0x10);
          } while ((__tree_node_base *)*plVar4 != p_Var6);
        }
      }
      else {
        do {
          plVar4 = plVar3;
          plVar3 = (long *)*plVar4;
        } while ((long *)*plVar4 != (long *)0x0);
      }
      if (*(__tree_node_base **)this == p_Var5) {
        *(long **)this = plVar4;
      }
      *(long *)(this + 0x10) = *(long *)(this + 0x10) + -1;
      __tree_remove<std::__tree_node_base<void*>*>(p_Var1,p_Var5);
      __tree<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>
      ::destroy((__tree<ATCFlightSegment_const*,std::less<ATCFlightSegment_const*>,std::allocator<ATCFlightSegment_const*>>
                 *)(p_Var5 + 0x28),*(__tree_node **)(p_Var5 + 0x30));
      operator_delete(p_Var5);
      return 1;
    }
  }
  return 0;
}


// 00247b90  ATCAircraftFlightPlan::ATCAircraftFlightPlan

/* ATCAircraftFlightPlan::ATCAircraftFlightPlan(ATCFlightType, std::string, std::string,
   units::value<float, units::scale<units::scale<units::scale<units::units::m, 100, 1>, 100, 254>,
   1, 12> >, std::string) */

void __thiscall ATCAircraftFlightPlan::ATCAircraftFlightPlan(void)

{
  ATCAircraftFlightPlan();
  return;
}


// 00247ba0  ATCFileFlightPlan

/* ATCFileFlightPlan(ATCAircraft*, ATCAircraftFlightPlan const&, std::string&) */

bool ATCFileFlightPlan(ATCAircraft *param_1,ATCAircraftFlightPlan *param_2,string *param_3)

{
  ATCFlightRoute local_48 [32];
  char local_28;
  
  if (param_1 == (ATCAircraft *)0x0) {
    param_1 = _gUsersAircraft;
  }
  (**(code **)(*(long *)param_1 + 0x268))(param_1);
  ATCFileFlightPlan(local_48,param_1,param_2,param_3);
  if (local_28 != '\0') {
    ATCFlightRoute::~ATCFlightRoute(local_48);
  }
  return local_28 != '\0';
}


// 00247c00  ATCAircraft::PreActivateIFRFlightplan

/* ATCAircraft::PreActivateIFRFlightplan() */

ulong ATCAircraft::PreActivateIFRFlightplan(void)

{
  long lVar1;
  ATCFlightRoute *this;
  ATCFlightRoute *this_00;
  uint uVar2;
  int iVar3;
  ATCWaypoint *pAVar4;
  char *pcVar5;
  undefined4 *puVar6;
  ATCWaypoint *pAVar7;
  int *piVar8;
  vec_apt_struct *pvVar9;
  long *plVar10;
  ulong uVar11;
  char cVar12;
  ATCAircraft *in_RDI;
  undefined4 uVar13;
  undefined4 in_XMM1_Da;
  undefined4 in_XMM1_Db;
  ATCFlightRoute local_b8 [32];
  long local_98;
  long *local_90;
  undefined8 local_88;
  undefined8 local_80;
  ulong local_78;
  undefined8 uStack_70;
  void *local_68;
  vec_apt_struct *local_58;
  undefined8 *local_50;
  undefined8 *local_48;
  undefined8 *local_40;
  vec_apt_struct *local_38;
  
  local_78 = 0;
  uStack_70 = 0;
  local_68 = (void *)0x0;
  if (in_RDI[0x1b8] == (ATCAircraft)0x0) {
    uVar11 = 0;
  }
  else {
    ATCFlightRoute::ATCFlightRoute(local_b8,in_RDI);
    ATCFlightRoute::StartEdit(local_b8);
    (**(code **)(*(long *)in_RDI + 0x268))();
    uVar2 = FileIFRFlightplan();
    ATCFlightRoute::FinishEdit(local_b8,true);
    if ((char)uVar2 == '\0') {
      uVar11 = 0;
      ATCFlightRoute::~ATCFlightRoute(local_b8);
    }
    else {
      local_58 = (vec_apt_struct *)0x0;
      local_38 = (vec_apt_struct *)0x0;
      iVar3 = ATCUtilsGetAptByAptID((string *)(in_RDI + 0x130),&local_58);
      plVar10 = (long *)(ulong)uVar2;
      if (iVar3 != -1) {
        ATCUtilsGetAptByAptID((string *)(in_RDI + 0x118),&local_38);
        ATCFlightRoute::operator=(*(ATCFlightRoute **)(in_RDI + 0x60),local_b8);
        this = *(ATCFlightRoute **)(in_RDI + 0x60);
        ATCFlightRoute::StartEdit(this);
        ATCRouteUtils::AppendVectorApt(*(ATCFlightRoute **)(in_RDI + 0x60),local_58);
        this_00 = *(ATCFlightRoute **)(in_RDI + 0x60);
        local_88 = (**(code **)(*(long *)in_RDI + 0x268))();
        local_80 = CONCAT44(in_XMM1_Db,in_XMM1_Da);
        local_50 = operator_new(0x10);
        local_48 = local_50 + 2;
        *local_50 = local_88;
        local_50[1] = local_80;
        local_40 = local_48;
        ATCFlightRoute::InsertFront(this_00,(vector *)&local_50);
        if (local_50 != (undefined8 *)0x0) {
          local_48 = local_50;
          operator_delete(local_50);
        }
        if (local_38 == (vec_apt_struct *)0x0) {
          pvVar9 = (vec_apt_struct *)0x0;
        }
        else {
          pAVar4 = (ATCWaypoint *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(in_RDI + 0x60));
          ATCWaypoint::SetNavaid(pAVar4,local_38);
          pvVar9 = local_38;
        }
        pcVar5 = (char *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(in_RDI + 0x60));
        cVar12 = -0x4b;
        if (pvVar9 != (vec_apt_struct *)0x0) {
          cVar12 = (char)pvVar9 + 'T';
        }
        std::string::assign(pcVar5);
        pAVar4 = (ATCWaypoint *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(in_RDI + 0x60));
        puVar6 = (undefined4 *)ATCWaypoint::GetNextSeg(pAVar4);
        if (puVar6 != (undefined4 *)0x0) {
          cVar12 = -0x41;
          std::string::assign((char *)(puVar6 + 0xc));
          *puVar6 = 3;
          puVar6[3] = 3;
        }
        local_50 = (undefined8 *)(**(code **)(*(long *)in_RDI + 0x268))();
        local_40 = (undefined8 *)CONCAT44(local_40._4_4_,*(undefined4 *)(in_RDI + 0x178));
        ATCControllerDb::FindControllerForGeoPt
                  ((GeoPoint3D *)&local_98,(bool)cVar12,SUB81(&local_50,0));
        uVar13 = ATCUtilsValidateIFRCruiseAlt
                           (in_RDI,(ATCAircraftFlightPlan *)(in_RDI + 0x110),
                            (ATCTransitionLayer *)(local_98 + 0x1e0));
        *(undefined4 *)(in_RDI + 0x1b0) = uVar13;
        for (pAVar4 = (ATCWaypoint *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(in_RDI + 0x60));
            pAVar7 = (ATCWaypoint *)ATCFlightRoute::GetEnd(*(ATCFlightRoute **)(in_RDI + 0x60)),
            pAVar4 != pAVar7; pAVar4 = (ATCWaypoint *)ATCWaypoint::GetNextPt(pAVar4)) {
          piVar8 = (int *)ATCWaypoint::GetNextSeg(pAVar4);
          if (((piVar8 != (int *)0x0) && (*piVar8 == 3)) && (piVar8[3] != 2)) {
            ATCAltUtils::AssignAlt
                      (((*(float *)(in_RDI + 0x1b0) * DAT_02536f10 * DAT_02536f14) / DAT_02525330) /
                       DAT_02525330,*(undefined8 *)(in_RDI + 0x60),piVar8,0,0);
          }
        }
        if (local_90 != (long *)0x0) {
          LOCK();
          plVar10 = local_90 + 1;
          lVar1 = *plVar10;
          *plVar10 = *plVar10 + -1;
          UNLOCK();
          if (lVar1 == 0) {
            (**(code **)(*local_90 + 0x10))(local_90);
            std::__shared_weak_count::__release_weak();
          }
        }
        ATCFlightRoute::FinishEdit(this,true);
        plVar10 = local_90;
      }
      uVar11 = CONCAT71((int7)((ulong)plVar10 >> 8),iVar3 != -1);
      ATCFlightRoute::~ATCFlightRoute(local_b8);
    }
    if ((local_78 & 1) != 0) {
      operator_delete(local_68);
    }
  }
  return uVar11 & 0xffffffff;
}


// 0024d380  ATCAircraftFlightPlan::~ATCAircraftFlightPlan

/* ATCAircraftFlightPlan::~ATCAircraftFlightPlan() */

void __thiscall ATCAircraftFlightPlan::~ATCAircraftFlightPlan(ATCAircraftFlightPlan *this)

{
  ~ATCAircraftFlightPlan(this);
  return;
}


// 00254d20  ATCSourceAircraft::PopulateFlightInfoFromVeh

/* WARNING: Type propagation algorithm not settling */
/* ATCSourceAircraft::PopulateFlightInfoFromVeh(bool) */

void __thiscall ATCSourceAircraft::PopulateFlightInfoFromVeh(ATCSourceAircraft *this,bool param_1)

{
  ulong local_b0;
  undefined8 uStack_a8;
  void *local_a0;
  ulong local_98;
  undefined8 uStack_90;
  void *local_88;
  ulong uStack_80;
  undefined8 local_78;
  void *pvStack_70;
  ulong local_68;
  undefined8 uStack_60;
  void *local_58;
  int local_50;
  ulong local_48;
  undefined8 uStack_40;
  void *local_38;
  
  local_48 = 0;
  uStack_40 = 0;
  local_38 = (void *)0x0;
  local_98 = 0;
  uStack_90 = 0;
  local_88 = (void *)0x0;
  uStack_80 = 0;
  local_78 = 0;
  pvStack_70 = (void *)0x0;
  local_68 = 0;
  uStack_60 = 0;
  local_58 = (void *)0x0;
  local_50 = 0xffffffff;
  std::string::operator=((string *)&uStack_80,(string *)(*(long *)(this + 0x420) + 0x5cc0));
  std::string::operator=((string *)&local_68,(string *)(*(long *)(this + 0x420) + 0x5cd8));
  local_50 = *(int *)(*(long *)(*(long *)(this + 0x420) + 0x5d08) +
                     (long)*(int *)(*(long *)(this + 0x428) + 0x34) * 4);
  std::string::operator=((string *)&local_98,(string *)(*(long *)(this + 0x420) + 0x5cf0));
  if (local_50 == -1) {
    std::string::assign((char *)&local_48);
  }
  else if (param_1) {
    ATCUtilsGenRandomUniqueFlightNumber(&local_b0);
    if ((local_48 & 1) != 0) {
      operator_delete(local_38);
    }
    local_38 = local_a0;
    local_48 = local_b0;
    uStack_40 = uStack_a8;
  }
  else {
    std::string::operator=
              ((string *)&local_48,
               (string *)
               ((long)*(int *)(*(long *)(this + 0x428) + 0x34) * 0x18 +
               *(long *)(*(long *)(this + 0x420) + 0x5d20)));
  }
  std::string::operator=((string *)(this + 0x200),(string *)&local_98);
  std::string::operator=((string *)(this + 0x218),(string *)&uStack_80);
  std::string::operator=((string *)(this + 0x230),(string *)&local_68);
  *(int *)(this + 0x248) = local_50;
  std::string::operator=((string *)(this + 0x250),(string *)&local_48);
  if ((local_48 & 1) != 0) {
    operator_delete(local_38);
  }
  if ((local_68 & 1) != 0) {
    operator_delete(local_58);
  }
  if ((uStack_80 & 1) != 0) {
    operator_delete(pvStack_70);
  }
  if ((local_98 & 1) != 0) {
    operator_delete(local_88);
  }
  return;
}


// 00271a60  ATCAircraft::IsVFRFlightFollowing

/* ATCAircraft::IsVFRFlightFollowing() const */

bool __thiscall ATCAircraft::IsVFRFlightFollowing(ATCAircraft *this)

{
  int *piVar1;
  
  if ((*(int *)(this + 0x68) == 1) && (*(int *)(this + 0x6c) == 0)) {
    piVar1 = (int *)ATCFlightRoute::GetStartSeg(*(ATCFlightRoute **)(this + 0x60));
    if (piVar1 != (int *)0x0) {
      return *piVar1 == 4;
    }
  }
  return false;
}


// 002730c0  ATCAiAircraft::InitFlightAtGate

/* ATCAiAircraft::InitFlightAtGate(int, int) */

void __thiscall ATCAiAircraft::InitFlightAtGate(ATCAiAircraft *this,int param_1,int param_2)

{
  long *plVar1;
  undefined1 auVar2 [16];
  long lVar3;
  undefined1 *puVar4;
  long lVar5;
  undefined4 uVar6;
  long local_68;
  long *local_60;
  undefined1 local_58 [16];
  float local_48;
  undefined4 uStack_44;
  undefined8 local_38;
  
  local_38 = CONCAT44(local_38._4_4_,param_1);
  lVar5 = (long)param_1 * 0xa0;
  auVar2 = **(undefined1 (**) [16])(_vec_apt + 0x10 + lVar5);
  local_58._8_4_ = auVar2._0_4_;
  local_58._0_8_ = auVar2._8_8_;
  local_58._12_4_ = auVar2._4_4_;
  local_48 = ((*(float *)(_vec_apt + 0x48 + lVar5) * DAT_02525330 * DAT_02525330) / DAT_02536f14) /
             DAT_02536f10;
  ATCControllerDb::FindControllerForGeoPt
            ((GeoPoint3D *)&local_68,SUB41(param_1,0),SUB81(local_58,0));
  if (local_68 == 0) {
    uVar6 = 0x4b0;
  }
  else {
    uVar6 = *(undefined4 *)(_vec_atc + 0x84 + (long)*(int *)(local_68 + 0x1c8) * 0xa0);
  }
  if (local_60 != (long *)0x0) {
    LOCK();
    plVar1 = local_60 + 1;
    lVar3 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar3 == 0) {
      (**(code **)(*local_60 + 0x10))(local_60);
      std::__shared_weak_count::__release_weak();
    }
  }
  *(undefined4 *)(*(long *)(this + 0x428) + 0x634) = uVar6;
  ATCSourceAircraft::InitFlightAtGate((ATCSourceAircraft *)this,(int)local_38,param_2);
  if (0.0 < atc_record_crumbs) {
    local_38 = DAT_0315d538;
    std::to_string((int)local_58);
    if ((local_58[0] & 1) == 0) {
      puVar4 = local_58 + 1;
    }
    else {
      puVar4 = (undefined1 *)CONCAT44(uStack_44,local_48);
    }
    lVar3 = *(long *)(this + 0x420);
    if ((*(byte *)(lVar3 + 0x5aa0) & 1) == 0) {
      lVar3 = lVar3 + 0x5aa1;
    }
    else {
      lVar3 = *(long *)(lVar3 + 0x5ab0);
    }
    _source_sim_log_write((int)local_38,1,"NTC","NATC %f %s INIT_GATE %s %d %s\n",puVar4,
                      _vec_apt + lVar5 + 0x54,param_2,lVar3);
    if ((local_58[0] & 1) != 0) {
      operator_delete((void *)CONCAT44(uStack_44,local_48));
    }
  }
  return;
}


// 002732a0  ATCSourceAircraft::InitFlightAtGate

/* ATCSourceAircraft::InitFlightAtGate(int, int) */

void __thiscall ATCSourceAircraft::InitFlightAtGate(ATCSourceAircraft *this,int param_1,int param_2)

{
  long *plVar1;
  long lVar2;
  ATCSourceAircraft *pAVar3;
  undefined4 uVar4;
  long local_90;
  long local_88;
  uint local_38;
  long local_30;
  long *local_28;
  
  local_90 = _vec_apt + (long)param_1 * 0xa0;
  local_88 = (long)param_2 * 0x20 + *(long *)(_vec_apt + 0x18 + (long)param_1 * 0xa0);
  local_38 = 1;
  init_sim::set_ai_start(&_init,*(undefined4 *)(this + 0x430),&local_90,0);
  if ((ulong)local_38 != 0xffffffff) {
    (*(code *)(&
              PTR___dispatch<std::__variant_detail::__dtor<std::__variant_detail::__traits<runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>,(std::__variant_detail::_Trait)1>::__destroy()::_lambda(auto:1&)_1_&&,std::__variant_detail::__base<(std::__variant_detail::_Trait)1,runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>&>_02ad36b0
              )[local_38])(&local_30,&local_90);
  }
  (**(code **)(*(long *)this + 0x450))(this);
  pAVar3 = this;
  (**(code **)(*(long *)this + 600))(&local_90);
  ATCControllerDb::FindControllerForGeoPt
            ((GeoPoint3D *)&local_30,SUB81(pAVar3,0),SUB81(&local_90,0));
  if (local_30 == 0) {
    uVar4 = 0x4b0;
  }
  else {
    uVar4 = *(undefined4 *)(_vec_atc + 0x84 + (long)*(int *)(local_30 + 0x1c8) * 0xa0);
  }
  if (local_28 != (long *)0x0) {
    LOCK();
    plVar1 = local_28 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*local_28 + 0x10))(local_28);
      std::__shared_weak_count::__release_weak();
    }
  }
  *(undefined4 *)(this + 0x2ac) = uVar4;
  *(undefined4 *)(this + 0x268) = 0;
  return;
}


// 00273420  ATCAiAircraft::InitFlightEnroute

/* ATCAiAircraft::InitFlightEnroute(GeoPoint3D const&, float, units::value<float,
   units::compose<units::scale<units::units::m, 1, 1852>,
   units::pow<units::scale<units::scale<units::units::s, 1, 60>, 1, 60>, -1, 1> > >) */

void __thiscall
ATCAiAircraft::InitFlightEnroute
          (float param_2,float param_2_00,ATCAiAircraft *this,undefined8 *param_1)

{
  long lVar1;
  undefined1 *puVar2;
  uint uVar3;
  long lVar4;
  long lVar5;
  byte local_50;
  undefined1 local_4f [15];
  undefined1 *local_40;
  float local_38;
  float local_34;
  double local_30;
  
  local_38 = param_2_00;
  local_34 = param_2;
  ATCSourceAircraft::InitFlightEnroute();
  local_30 = DAT_0315d538;
  lVar1 = rand_gen();
  lVar4 = *(long *)(lVar1 + 0x9c0);
  lVar5 = lVar4 + ((lVar4 + 1U) / 0x270) * -0x270 + 1;
  uVar3 = *(uint *)(lVar1 + lVar5 * 4);
  uVar3 = (uVar3 & 1) * -0x66f74f21 ^
          *(uint *)(lVar1 + (((lVar4 + 0x18dU) / 0x270) * -0x270 + lVar4 + 0x18d) * 4) ^
          (uVar3 & 0x7ffffffe | *(uint *)(lVar1 + lVar4 * 4) & 0x80000000) >> 1;
  *(uint *)(lVar1 + lVar4 * 4) = uVar3;
  uVar3 = uVar3 >> 0xb ^ uVar3;
  *(long *)(lVar1 + 0x9c0) = lVar5;
  uVar3 = (uVar3 & 0x13a58ad) << 7 ^ uVar3;
  uVar3 = (uVar3 & 0x1df8c) << 0xf ^ uVar3;
  *(double *)(this + 0x5d0) =
       local_30 - (double)((float)(uVar3 >> 0x12 ^ uVar3) * DAT_025246c8 * DAT_0253ad40 + 0.0);
  if (0.0 < atc_record_crumbs) {
    local_30 = DAT_0315d538;
    std::to_string((int)&local_50);
    puVar2 = local_40;
    if ((local_50 & 1) == 0) {
      puVar2 = local_4f;
    }
    lVar4 = *(long *)(this + 0x420);
    if ((*(byte *)(lVar4 + 0x5aa0) & 1) == 0) {
      lVar4 = lVar4 + 0x5aa1;
    }
    else {
      lVar4 = *(long *)(lVar4 + 0x5ab0);
    }
    _source_sim_log_write(local_30,param_1[1],*param_1,
                      (double)(((*(float *)(param_1 + 2) * DAT_02536f10 * DAT_02536f14) /
                               DAT_02525330) / DAT_02525330),(double)local_34,(double)local_38,1,
                      "NTC","NATC %f %s INIT_AIR %lf %lf %lf %f %f %s\n",puVar2,lVar4);
    if ((local_50 & 1) != 0) {
      operator_delete(local_40);
    }
  }
  return;
}


// 00273650  ATCSourceAircraft::InitFlightEnroute

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* ATCSourceAircraft::InitFlightEnroute(GeoPoint3D const&, float, units::value<float,
   units::compose<units::scale<units::units::m, 1, 1852>,
   units::pow<units::scale<units::scale<units::units::s, 1, 60>, 1, 60>, -1, 1> > >) */

void __thiscall
ATCSourceAircraft::InitFlightEnroute
          (undefined8 param_1_00,float param_2,ATCSourceAircraft *this,undefined4 *param_1)

{
  long *plVar1;
  undefined8 uVar2;
  long lVar3;
  ATCSourceAircraft *pAVar4;
  undefined4 uVar5;
  undefined8 in_XMM0_Qb;
  undefined1 auVar6 [16];
  undefined4 local_98;
  undefined4 uStack_94;
  undefined4 uStack_90;
  undefined4 uStack_8c;
  double local_88;
  double dStack_80;
  undefined8 local_78;
  double local_70;
  undefined4 local_68;
  uint local_40;
  long local_38;
  long *local_30;
  
  local_98 = *param_1;
  uStack_94 = param_1[1];
  uStack_90 = param_1[2];
  uStack_8c = param_1[3];
  auVar6._8_8_ = in_XMM0_Qb;
  auVar6._0_8_ = param_1_00;
  auVar6 = insertps(ZEXT416((uint)((((float)param_1[4] * DAT_02536f10 * DAT_02536f14) / DAT_02525330
                                   ) / DAT_02525330)),auVar6,0x10);
  local_88 = (double)auVar6._0_4_;
  dStack_80 = (double)auVar6._4_4_;
  local_70 = (double)param_2 / _DAT_02520b88;
  uVar2 = *(undefined8 *)(*(long *)(this + 0x428) + 0x6640);
  local_78 = 0;
  local_68 = 0;
  local_40 = 3;
  init_sim::set_ai_start(&_init,*(undefined4 *)(this + 0x430),&local_98,0);
  if ((ulong)local_40 != 0xffffffff) {
    (*(code *)(&
              PTR___dispatch<std::__variant_detail::__dtor<std::__variant_detail::__traits<runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>,(std::__variant_detail::_Trait)1>::__destroy()::_lambda(auto:1&)_1_&&,std::__variant_detail::__base<(std::__variant_detail::_Trait)1,runway_start_spec,ramp_start_spec,lle_ground_start_spec,lle_air_start_spec,boat_start_spec>&>_02ad36b0
              )[local_40])(&local_38,&local_98);
  }
  (**(code **)(*(long *)this + 0x450))(this);
  pAVar4 = this;
  (**(code **)(*(long *)this + 600))(&local_98);
  ATCControllerDb::FindControllerForGeoPt
            ((GeoPoint3D *)&local_38,SUB81(pAVar4,0),SUB81(&local_98,0));
  if (local_38 == 0) {
    uVar5 = 0x4b0;
  }
  else {
    uVar5 = *(undefined4 *)(_vec_atc + 0x84 + (long)*(int *)(local_38 + 0x1c8) * 0xa0);
  }
  if (local_30 != (long *)0x0) {
    LOCK();
    plVar1 = local_30 + 1;
    lVar3 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar3 == 0) {
      (**(code **)(*local_30 + 0x10))(local_30);
      std::__shared_weak_count::__release_weak();
    }
  }
  *(undefined4 *)(this + 0x2ac) = uVar5;
  lVar3 = *(long *)(this + 0x428);
  *(undefined8 *)(lVar3 + 0x6648) = uVar2;
  *(undefined8 *)(lVar3 + 0x6640) = uVar2;
  *(undefined4 *)(this + 0x268) = 7;
  return;
}


// 00275160  ATCAircraftFlightPlan::to_debug_string

/* ATCAircraftFlightPlan::to_debug_string() const */

void ATCAircraftFlightPlan::to_debug_string(void)

{
  byte bVar1;
  uint uVar2;
  uint uVar3;
  uint *in_RSI;
  char *in_RDI;
  long lVar4;
  long lVar5;
  long lVar6;
  undefined8 *puVar7;
  byte local_30;
  undefined8 local_2f;
  undefined1 local_27;
  undefined8 *local_20;
  
  if ((char)in_RSI[0x1b] == '\0') {
    local_30 = 0x10;
    local_2f = 0x656e6f4e3d716552;
    local_27 = 0;
    bVar1 = (byte)in_RSI[2];
  }
  else {
    stl_printf((char *)&local_30,"Req=%d",(ulong)(uint)(int)(float)in_RSI[0x1a]);
    bVar1 = (byte)in_RSI[2];
  }
  if ((bVar1 & 1) == 0) {
    lVar4 = (long)in_RSI + 9;
    bVar1 = (byte)in_RSI[8];
  }
  else {
    lVar4 = *(long *)(in_RSI + 6);
    bVar1 = (byte)in_RSI[8];
  }
  if ((bVar1 & 1) == 0) {
    lVar5 = (long)in_RSI + 0x21;
    bVar1 = (byte)in_RSI[0x14];
  }
  else {
    lVar5 = *(long *)(in_RSI + 0xc);
    bVar1 = (byte)in_RSI[0x14];
  }
  if ((bVar1 & 1) == 0) {
    lVar6 = (long)in_RSI + 0x51;
    uVar2 = *in_RSI;
    uVar3 = in_RSI[1];
  }
  else {
    lVar6 = *(long *)(in_RSI + 0x18);
    uVar2 = *in_RSI;
    uVar3 = in_RSI[1];
  }
  puVar7 = local_20;
  if ((local_30 & 1) == 0) {
    puVar7 = &local_2f;
  }
  stl_printf(in_RDI,"[Type=%d Status=%d Dep=%s Arr=%s Route=\'%s\' %s Assign=%d]",(ulong)uVar2,
             (ulong)uVar3,lVar4,lVar5,lVar6,puVar7,(ulong)(uint)(int)(float)in_RSI[0x28]);
  if ((local_30 & 1) != 0) {
    operator_delete(local_20);
  }
  return;
}


// 00275250  ATCAircraftFlightPlan::ATCAircraftFlightPlan

/* ATCAircraftFlightPlan::ATCAircraftFlightPlan(ATCFlightType, std::string, std::string,
   units::value<float, units::scale<units::scale<units::scale<units::units::m, 100, 1>, 100, 254>,
   1, 12> >, std::string) */

void __thiscall
ATCAircraftFlightPlan::ATCAircraftFlightPlan
          (undefined4 param_1,ATCAircraftFlightPlan *this,undefined4 param_3,string *param_4,
          string *param_5,string *param_6)

{
  this[0x6c] = (ATCAircraftFlightPlan)0x0;
  *(undefined8 *)(this + 8) = 0;
  *(undefined8 *)(this + 0x10) = 0;
  *(undefined8 *)(this + 0x18) = 0;
  *(undefined8 *)(this + 0x20) = 0;
  *(undefined8 *)(this + 0x28) = 0;
  *(undefined8 *)(this + 0x30) = 0;
  *(undefined8 *)(this + 0x38) = 0;
  *(undefined8 *)(this + 0x40) = 0;
  *(undefined8 *)(this + 0x48) = 0;
  *(undefined8 *)(this + 0x50) = 0;
  *(undefined8 *)(this + 0x58) = 0;
  *(undefined8 *)(this + 0x60) = 0;
  this[0x68] = (ATCAircraftFlightPlan)0x0;
  *(undefined8 *)(this + 0x70) = 0;
  *(undefined8 *)(this + 0x78) = 0;
  *(undefined8 *)(this + 0x80) = 0;
  *(undefined8 *)(this + 0x88) = 0;
  *(undefined8 *)(this + 0x90) = 0;
  *(undefined8 *)(this + 0x98) = 0;
  *(undefined8 *)(this + 0x9d) = 0;
  *(undefined4 *)this = param_3;
  *(undefined4 *)(this + 4) = 0;
  std::string::operator=((string *)(this + 8),param_4);
  std::string::operator=((string *)(this + 0x20),param_5);
  *(undefined4 *)(this + 0x68) = param_1;
  if (this[0x6c] == (ATCAircraftFlightPlan)0x0) {
    this[0x6c] = (ATCAircraftFlightPlan)0x1;
  }
  std::string::operator=((string *)(this + 0x50),param_6);
  return;
}


// 00276500  ATCAircraftFlightInfo::~ATCAircraftFlightInfo

/* ATCAircraftFlightInfo::~ATCAircraftFlightInfo() */

void __thiscall ATCAircraftFlightInfo::~ATCAircraftFlightInfo(ATCAircraftFlightInfo *this)

{
  ATCAircraftFlightInfo AVar1;
  
  if (((byte)this[0x50] & 1) == 0) {
    AVar1 = this[0x30];
  }
  else {
    operator_delete(*(void **)(this + 0x60));
    AVar1 = this[0x30];
  }
  if (((byte)AVar1 & 1) == 0) {
    AVar1 = this[0x18];
  }
  else {
    operator_delete(*(void **)(this + 0x40));
    AVar1 = this[0x18];
  }
  if (((byte)AVar1 & 1) == 0) {
    AVar1 = *this;
  }
  else {
    operator_delete(*(void **)(this + 0x28));
    AVar1 = *this;
  }
  if (((byte)AVar1 & 1) != 0) {
    operator_delete(*(void **)(this + 0x10));
    return;
  }
  return;
}


// 00276570  std::optional<ATCAircraftFlightPlan>::~optional

/* std::optional<ATCAircraftFlightPlan>::~optional() */

void __thiscall
std::optional<ATCAircraftFlightPlan>::~optional(optional<ATCAircraftFlightPlan> *this)

{
  if (this[0xa8] != (optional<ATCAircraftFlightPlan>)0x0) {
    ATCAircraftFlightPlan::~ATCAircraftFlightPlan((ATCAircraftFlightPlan *)this);
    return;
  }
  return;
}


// 002797d0  ATCAircraft::FileIFRFlightplan

/* WARNING: Type propagation algorithm not settling */
/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&, ATCFlightRoute&)
    */

ulong ATCAircraft::FileIFRFlightplan
                (void *param_1_00,ulong param_2,ATCAircraft *param_1,ATCAircraftFlightPlan *param_4,
                byte *param_5,ATCFlightRoute *param_6)

{
  long *plVar1;
  byte bVar2;
  ATCAircraft *pAVar3;
  undefined8 uVar4;
  undefined8 uVar5;
  long *plVar6;
  undefined1 auVar7 [16];
  undefined2 uVar8;
  float fVar9;
  float fVar10;
  UTL_geoid UVar11;
  void *pvVar12;
  ATCFlightRoute *this;
  Route *pRVar13;
  ATCAircraft AVar14;
  ATCAircraft AVar15;
  undefined7 uVar16;
  char cVar17;
  bool bVar18;
  bool bVar19;
  int iVar20;
  uint uVar21;
  int iVar22;
  undefined4 uVar23;
  void *pvVar24;
  ulong uVar25;
  size_t sVar26;
  vec_nav_struct *pvVar27;
  vec_fix_struct *pvVar28;
  awy_node_struct *paVar29;
  awy_node_struct *paVar30;
  uint *puVar31;
  undefined4 extraout_var;
  undefined8 uVar32;
  undefined1 (*pauVar33) [16];
  byte *pbVar34;
  ATCWaypoint *pAVar35;
  GeoPoint2D *pGVar36;
  ATCWaypoint *this_00;
  GeoPoint2D *pGVar37;
  undefined8 *puVar38;
  undefined8 *puVar39;
  undefined1 *puVar40;
  ulong *puVar41;
  ATCAircraftFlightPlan *pAVar42;
  byte bVar43;
  vec_apt_struct *pvVar44;
  size_t sVar45;
  long lVar46;
  int extraout_EDX;
  int extraout_EDX_00;
  string *psVar47;
  __tree_node *p_Var48;
  ATCControllerCab *this_01;
  byte *pbVar49;
  byte *pbVar50;
  byte *pbVar51;
  byte *pbVar52;
  ulong uVar53;
  ATCAircraft *pAVar54;
  undefined1 *puVar55;
  dev_t dev;
  char *pcVar56;
  uint *puVar57;
  vec_fix_struct *pvVar58;
  __tree_node *p_Var59;
  __tree_node *p_Var60;
  undefined1 *puVar61;
  ulong uVar62;
  long lVar63;
  ulong uVar64;
  ATCAircraftFlightPlan AVar65;
  long *plVar66;
  long lVar67;
  void *pvVar68;
  ATCAircraftFlightPlan AVar69;
  ATCAircraftFlightPlan AVar70;
  undefined4 *puVar71;
  Route *this_02;
  Route *pRVar72;
  float fVar73;
  float fVar74;
  float fVar75;
  double dVar76;
  double dVar79;
  undefined1 auVar77 [16];
  undefined1 auVar78 [16];
  UTL_geoid local_6a0;
  undefined1 local_69f [15];
  undefined1 *local_690;
  start_loc_spec *local_3a0;
  ATCAircraftFlightPlan *local_398;
  byte *local_390;
  undefined8 local_388;
  undefined8 uStack_380;
  undefined1 local_378;
  string local_370;
  undefined1 local_36f [7];
  size_t local_368;
  undefined1 *local_360;
  __tree_node **local_358;
  __tree_node *local_350;
  undefined8 uStack_348;
  undefined8 local_340;
  undefined8 local_338;
  string *local_330;
  ATCAircraftFlightPlan *local_328;
  __tree_node *local_320;
  __tree_node *local_318;
  undefined8 uStack_310;
  ATCAircraftFlightPlan local_308;
  ATCAircraftFlightPlan AStack_307;
  undefined6 uStack_306;
  undefined2 uStack_300;
  undefined6 uStack_2fe;
  void *local_2f8;
  undefined1 local_2e8 [16];
  void *local_2d8;
  float local_2d0;
  float local_2cc;
  string *local_2c8;
  string *local_2c0;
  ATCControllerCab *local_2b8;
  vec_apt_struct *local_2b0;
  string *local_2a8;
  ulong local_2a0;
  string *local_298;
  vec_apt_struct *local_290;
  string *local_288;
  vec_apt_struct *local_280;
  ATCAircraft *local_278;
  ATCAircraftFlightPlan *local_270;
  vec_nav_struct *local_268;
  __tree_node local_260;
  byte *local_258;
  ATCFlightRoute *local_250;
  undefined1 local_248 [31];
  char local_229;
  void *local_228;
  byte *local_220;
  awy_node_struct *local_218;
  long local_210;
  ulong local_208;
  long *local_200;
  byte *local_1f8;
  byte *pbStack_1f0;
  undefined8 local_1e8;
  ATCAircraftFlightPlan *local_1d8;
  byte *local_1d0;
  undefined1 local_1c8 [16];
  void *local_1b8;
  undefined8 local_1a8;
  undefined6 uStack_1a0;
  undefined6 local_198;
  undefined2 uStack_192;
  undefined6 local_190;
  undefined2 uStack_18a;
  undefined8 local_188;
  undefined8 uStack_180;
  undefined1 local_178;
  undefined7 uStack_177;
  string local_170;
  undefined4 uStack_16f;
  undefined1 uStack_16b;
  undefined2 uStack_16a;
  undefined6 local_168;
  undefined2 uStack_162;
  undefined4 *local_160;
  undefined1 local_158 [14];
  undefined2 uStack_14a;
  char *local_148;
  undefined8 uStack_140;
  undefined1 local_138 [16];
  undefined1 local_128 [16];
  undefined1 local_118;
  undefined1 local_110 [16];
  char local_100;
  undefined1 local_f8;
  undefined8 local_f0;
  undefined1 local_e8 [14];
  undefined2 uStack_da;
  char *local_d8;
  ATCAircraft local_c8;
  uint uStack_c7;
  char cStack_c3;
  char cStack_c2;
  char cStack_c1;
  ATCAircraft AStack_c0;
  undefined7 uStack_bf;
  ATCAircraft local_b8;
  undefined1 uStack_b7;
  undefined6 uStack_b6;
  undefined1 uStack_b0;
  undefined7 uStack_af;
  function *local_a8;
  undefined1 uStack_a0;
  undefined7 uStack_9f;
  undefined1 local_98 [16];
  ulong local_88;
  undefined1 local_80 [16];
  ulong local_70;
  undefined1 local_68;
  undefined8 local_60;
  undefined1 local_58 [16];
  undefined1 *local_48;
  long lStack_38;
  
  lStack_38 = *(long *)PTR____stack_chk_guard_02ac0540;
  local_278 = param_1;
  local_228 = param_1_00;
  local_208 = param_2;
  local_1d8 = param_4;
  if ((_atc_debug_acfCmds != 0.0) || (NAN(_atc_debug_acfCmds))) {
    (**(code **)(*(long *)param_1 + 0x3f8))(&local_6a0,param_1);
    puVar55 = local_690;
    UVar11 = local_6a0;
    GetStatusText(&local_c8,*(undefined4 *)(param_1 + 0x268));
    if (((byte)UVar11 & 1) == 0) {
      puVar55 = local_69f;
    }
    if (((byte)local_c8 & 1) == 0) {
      puVar31 = &uStack_c7;
    }
    else {
      puVar31 = (uint *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
    }
    _source_sim_log_write(0,"ATC","%s: %s() at status %s",puVar55,"FileIFRFlightplan",puVar31);
    if (((byte)local_c8 & 1) != 0) {
      operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
    }
    if (((byte)local_6a0 & 1) != 0) {
      operator_delete(local_690);
    }
  }
  local_248._0_16_ = ZEXT816(0);
  local_2b0 = (vec_apt_struct *)0x0;
  local_290 = (vec_apt_struct *)0x0;
  local_1f8 = (byte *)0x0;
  pbStack_1f0 = (byte *)0x0;
  local_1e8 = 0;
  local_250 = param_6;
  local_220 = param_5;
  cVar17 = (**(code **)(*(long *)local_278 + 0x1a0))(local_278);
  local_320 = (__tree_node *)&local_318;
  local_318 = (__tree_node *)0x0;
  uStack_310 = 0;
  local_358 = &local_350;
  local_350 = (__tree_node *)0x0;
  uStack_348 = 0;
  pvVar24 = (void *)REN_geoid::instance();
  _memcpy(&local_6a0,pvVar24,0x300);
  *(undefined4 *)(local_1d8 + 4) = 0;
  if (((byte)local_1d8[8] & 1) == 0) {
    if ((byte)local_1d8[8] >> 1 != 0) goto LAB_002799a6;
LAB_00279a4b:
    local_2c8 = (string *)(local_1d8 + 8);
    plVar66 = (long *)0x0;
    this_01 = (ATCControllerCab *)0x0;
  }
  else {
    if (*(long *)(local_1d8 + 0x10) == 0) goto LAB_00279a4b;
LAB_002799a6:
    local_2c8 = (string *)(local_1d8 + 8);
    ATCUtilsGetAptByAptID(local_2c8,&local_2b0);
    ATCControllerDb::FindOrCreateControllerCab((int)(function *)&local_c8);
    uVar16 = uStack_bf;
    AVar15 = AStack_c0;
    AVar14 = local_c8;
    this_01 = (ATCControllerCab *)
              CONCAT17(cStack_c1,
                       CONCAT16(cStack_c2,CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))));
    plVar66 = (long *)CONCAT71(uStack_bf,AStack_c0);
    if (*(int *)(this_01 + 0x4f8) != 4) {
      if (plVar66 != (long *)0x0) {
        LOCK();
        plVar66[1] = plVar66[1] + 1;
        UNLOCK();
      }
      local_c8 = (ATCAircraft)0xe8;
      uStack_c7 = 0x2ad42;
      cStack_c3 = '\0';
      cStack_c2 = '\0';
      cStack_c1 = '\0';
      AStack_c0 = AVar14;
      uStack_bf = (undefined7)((ulong)this_01 >> 8);
      local_b8 = AVar15;
      uStack_b7 = (undefined1)uVar16;
      uStack_b6 = (undefined6)((uint7)uVar16 >> 8);
      local_a8 = (function *)&local_c8;
      UTL_completely_drain_work_until((function *)&local_c8);
      if ((function *)&local_c8 == local_a8) {
        (**(code **)(*(long *)local_a8 + 0x20))();
      }
      else if (local_a8 != (function *)0x0) {
        (**(code **)(*(long *)local_a8 + 0x28))();
      }
    }
    ATCControllerCab::GetActiveRwys(this_01,(set *)&local_320,(set *)&local_358);
  }
  local_288 = (string *)(local_1d8 + 0x20);
  iVar20 = ATCUtilsGetAptByAptID(local_288,&local_290);
  this = local_250;
  if (iVar20 == -1) {
    if (((byte)local_1d8[0x20] & 1) == 0) {
      psVar47 = local_288 + 1;
    }
    else {
      psVar47 = *(string **)(local_1d8 + 0x30);
    }
    pcVar56 = "Arrival Airport \'%s\' invalid!";
  }
  else if (local_290[0x51] == (vec_apt_struct)0x11) {
    if (((byte)local_1d8[0x20] & 1) == 0) {
      psVar47 = local_288 + 1;
    }
    else {
      psVar47 = *(string **)(local_1d8 + 0x30);
    }
    pcVar56 = "Arrival airport \'%s\' is a heliport; you can only fly into airports.";
  }
  else {
    if (local_290[0x51] != (vec_apt_struct)0x10) {
      local_200 = plVar66;
      ATCFlightRoute::StartEdit(local_250);
      ATCFlightRoute::Clear(this);
      local_248._8_8_ = local_208;
      local_248._0_8_ = local_228;
      local_270 = local_1d8 + 0x51;
      if (((byte)local_1d8[0x50] & 1) == 0) {
        uVar53 = (ulong)((byte)local_1d8[0x50] >> 1);
        pAVar42 = local_270;
      }
      else {
        uVar53 = *(ulong *)(local_1d8 + 0x58);
        pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
      }
      local_340 = **(undefined8 **)(local_290 + 0x10);
      local_338 = (*(undefined8 **)(local_290 + 0x10))[1];
      local_2b8 = this_01;
      str_tokenize(&local_c8,pAVar42,uVar53," ",1);
      pbVar50 = local_1f8;
      pbVar34 = pbStack_1f0;
      if (local_1f8 != (byte *)0x0) {
        while (pbVar49 = pbVar34, pbVar49 != pbVar50) {
          pbVar34 = pbVar49 + -0x18;
          if ((pbVar49[-0x18] & 1) != 0) {
            operator_delete(*(void **)(pbVar49 + -8));
          }
        }
        pbStack_1f0 = pbVar50;
        operator_delete(local_1f8);
      }
      pbVar50 = (byte *)CONCAT17(cStack_c1,
                                 CONCAT16(cStack_c2,CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))
                                         ));
      pbStack_1f0 = (byte *)CONCAT71(uStack_bf,AStack_c0);
      local_1e8 = CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
      local_229 = cVar17;
      local_1f8 = pbVar50;
      pbVar34 = pbStack_1f0;
      if (pbVar50 != pbStack_1f0) {
        if (((byte)local_1d8[8] & 1) == 0) {
          if ((byte)local_1d8[8] >> 1 != 0) goto LAB_00279cfd;
LAB_00279e02:
          pbVar50 = pbStack_1f0;
          pbVar34 = pbStack_1f0;
          if (local_1f8 == pbStack_1f0) goto LAB_00279f25;
        }
        else {
          if (*(long *)(local_1d8 + 0x10) == 0) goto LAB_00279e02;
LAB_00279cfd:
          std::operator+((string *)&local_c8,(char *)local_2c8);
          AVar14 = local_c8;
          puVar31 = (uint *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
          if (((byte)local_c8 & 1) == 0) {
            uVar53 = (ulong)((byte)local_c8 >> 1);
            puVar57 = &uStack_c7;
            bVar43 = *pbVar50;
            if ((bVar43 & 1) != 0) goto LAB_00279d3e;
LAB_00279d80:
            pbVar34 = pbVar50 + 1;
            if (uVar53 <= bVar43 >> 1) goto LAB_00279d4b;
LAB_00279d8c:
            bVar18 = false;
          }
          else {
            uVar53 = CONCAT71(uStack_bf,AStack_c0);
            bVar43 = *pbVar50;
            puVar57 = puVar31;
            if ((bVar43 & 1) == 0) goto LAB_00279d80;
LAB_00279d3e:
            pbVar34 = *(byte **)(pbVar50 + 0x10);
            if (*(ulong *)(pbVar50 + 8) < uVar53) goto LAB_00279d8c;
LAB_00279d4b:
            if ((uVar53 == 0) || (iVar20 = _memcmp(pbVar34,puVar57,uVar53), iVar20 == 0)) {
              iVar20 = 0;
            }
            bVar18 = iVar20 == 0;
          }
          if (((byte)AVar14 & 1) != 0) {
            operator_delete(puVar31);
          }
          pbVar34 = pbStack_1f0;
          if (!bVar18) goto LAB_00279e02;
          pbVar49 = local_1f8 + 0x18;
          pbVar50 = local_1f8;
          pbVar51 = local_1f8;
          if (pbVar49 == pbStack_1f0) {
LAB_00279f68:
            do {
              pbVar34 = pbVar49 + -0x18;
              if ((pbVar49[-0x18] & 1) != 0) {
                operator_delete(*(void **)(pbVar49 + -8));
              }
              pbVar49 = pbVar34;
            } while (pbVar34 != pbVar50);
          }
          else {
            do {
              if ((*pbVar51 & 1) != 0) {
                operator_delete(*(void **)(pbVar51 + 0x10));
              }
              pbVar50 = pbVar51 + 0x18;
              *(undefined8 *)(pbVar51 + 0x10) = *(undefined8 *)(pbVar51 + 0x28);
              *(undefined8 *)pbVar51 = *(undefined8 *)(pbVar51 + 0x18);
              *(undefined8 *)(pbVar51 + 8) = *(undefined8 *)(pbVar51 + 0x20);
              pbVar51[0x18] = 0;
              pbVar51[0x19] = 0;
              pbVar49 = pbVar51 + 0x30;
              pbVar51 = pbVar50;
            } while (pbVar49 != pbVar34);
            pbVar49 = pbStack_1f0;
            if (pbVar50 != pbStack_1f0) goto LAB_00279f68;
          }
          pbStack_1f0 = pbVar50;
          pbVar34 = pbVar50;
          if (local_1f8 == pbVar50) goto LAB_00279f25;
        }
        pbVar50 = pbStack_1f0;
        pbVar34 = pbStack_1f0;
        if (((byte)local_1d8[0x20] & 1) == 0) {
          if ((byte)local_1d8[0x20] >> 1 != 0) goto LAB_00279e38;
        }
        else if (*(long *)(local_1d8 + 0x28) != 0) {
LAB_00279e38:
          std::operator+((string *)&local_c8,(char *)local_288);
          AVar14 = local_c8;
          puVar31 = (uint *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
          if (((byte)local_c8 & 1) == 0) {
            uVar53 = (ulong)((byte)local_c8 >> 1);
            puVar57 = &uStack_c7;
            bVar43 = pbVar50[-0x18];
            if ((bVar43 & 1) != 0) goto LAB_00279e7c;
LAB_00279eba:
            pbVar34 = pbVar50 + -0x17;
            if (uVar53 <= bVar43 >> 1) goto LAB_00279e89;
LAB_00279ec6:
            bVar18 = false;
          }
          else {
            uVar53 = CONCAT71(uStack_bf,AStack_c0);
            bVar43 = pbVar50[-0x18];
            puVar57 = puVar31;
            if ((bVar43 & 1) == 0) goto LAB_00279eba;
LAB_00279e7c:
            pbVar34 = *(byte **)(pbVar50 + -8);
            if (*(ulong *)(pbVar50 + -0x10) < uVar53) goto LAB_00279ec6;
LAB_00279e89:
            if ((uVar53 == 0) || (iVar20 = _memcmp(pbVar34,puVar57,uVar53), iVar20 == 0)) {
              iVar20 = 0;
            }
            bVar18 = iVar20 == 0;
          }
          if (((byte)AVar14 & 1) != 0) {
            operator_delete(puVar31);
          }
          pbVar50 = pbStack_1f0;
          pbVar34 = pbStack_1f0;
          if ((bVar18) &&
             (pbVar50 = pbStack_1f0 + -0x18, pbVar34 = pbVar50, (pbStack_1f0[-0x18] & 1) != 0)) {
            operator_delete(*(void **)(pbStack_1f0 + -8));
          }
        }
      }
LAB_00279f25:
      pbStack_1f0 = pbVar34;
      pbVar34 = local_1f8;
      if (local_1f8 == pbVar50) {
LAB_0027a0e2:
        pbVar34 = pbStack_1f0;
        if (local_1f8 != pbVar50) {
LAB_0027a0ef:
          pbVar34 = pbStack_1f0;
          if (((byte)local_1d8[0x20] & 1) == 0) {
            if ((byte)local_1d8[0x20] >> 1 != 0) goto LAB_0027a118;
          }
          else if (*(long *)(local_1d8 + 0x28) != 0) {
LAB_0027a118:
            std::string::string((string *)&local_c8,local_288,1,3,(allocator *)local_288);
            bVar43 = (byte)local_c8 & 1;
            if (bVar43 == 0) {
              uVar53 = (ulong)((byte)local_c8 >> 1);
              puVar31 = &uStack_c7;
              bVar2 = pbVar50[-0x18];
              if ((bVar2 & 1) != 0) goto LAB_0027a165;
LAB_0027a183:
              uVar25 = (ulong)(bVar2 >> 1);
              pbVar50 = pbVar50 + -0x17;
            }
            else {
              puVar31 = (uint *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
              uVar53 = CONCAT71(uStack_bf,AStack_c0);
              bVar2 = pbVar50[-0x18];
              if ((bVar2 & 1) == 0) goto LAB_0027a183;
LAB_0027a165:
              uVar25 = *(ulong *)(pbVar50 + -0x10);
              pbVar50 = *(byte **)(pbVar50 + -8);
            }
            uVar62 = uVar25;
            if (uVar53 < uVar25) {
              uVar62 = uVar53;
            }
            if (uVar62 == 0) {
              if (uVar25 == uVar53) goto LAB_0027a1b4;
              bVar18 = false;
            }
            else {
              iVar20 = _memcmp(pbVar50,puVar31,uVar62);
              bVar18 = false;
              if ((iVar20 == 0) && (bVar18 = false, uVar25 == uVar53)) {
LAB_0027a1b4:
                iVar20 = ATCUtilsGetNavByName
                                   (local_248._0_8_,local_248._8_4_,&local_6a0,pbStack_1f0 + -0x18,
                                    0xffffffff,0);
                bVar43 = (byte)local_c8 & 1;
                bVar18 = iVar20 == -1;
              }
            }
            if (bVar43 != 0) {
              operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
            }
            pbVar50 = pbStack_1f0;
            pbVar34 = pbStack_1f0;
            if ((bVar18) &&
               (pbVar50 = pbStack_1f0 + -0x18, pbVar34 = pbVar50, (pbStack_1f0[-0x18] & 1) != 0)) {
              operator_delete(*(void **)(pbStack_1f0 + -8));
            }
          }
        }
      }
      else {
        if (((byte)local_1d8[8] & 1) == 0) {
          if ((byte)local_1d8[8] >> 1 != 0) goto LAB_00279f89;
          goto LAB_0027a0e2;
        }
        if (*(long *)(local_1d8 + 0x10) == 0) goto LAB_0027a0e2;
LAB_00279f89:
        std::string::string((string *)&local_c8,local_2c8,1,3,(allocator *)local_2c8);
        bVar43 = (byte)local_c8 & 1;
        if (bVar43 == 0) {
          uVar53 = (ulong)((byte)local_c8 >> 1);
          puVar31 = &uStack_c7;
          bVar2 = *pbVar34;
          if ((bVar2 & 1) != 0) goto LAB_00279fd1;
LAB_00279fee:
          uVar25 = (ulong)(bVar2 >> 1);
          pbVar34 = pbVar34 + 1;
        }
        else {
          puVar31 = (uint *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
          uVar53 = CONCAT71(uStack_bf,AStack_c0);
          bVar2 = *pbVar34;
          if ((bVar2 & 1) == 0) goto LAB_00279fee;
LAB_00279fd1:
          uVar25 = *(ulong *)(pbVar34 + 8);
          pbVar34 = *(byte **)(pbVar34 + 0x10);
        }
        uVar62 = uVar25;
        if (uVar53 < uVar25) {
          uVar62 = uVar53;
        }
        if (uVar62 == 0) {
          if (uVar25 == uVar53) goto LAB_0027a023;
          bVar18 = false;
        }
        else {
          iVar20 = _memcmp(pbVar34,puVar31,uVar62);
          bVar18 = false;
          if ((iVar20 == 0) && (bVar18 = false, uVar25 == uVar53)) {
LAB_0027a023:
            iVar20 = ATCUtilsGetNavByName
                               (local_248._0_8_,local_248._8_4_,&local_6a0,local_1f8,0xffffffff,0);
            bVar43 = (byte)local_c8 & 1;
            bVar18 = iVar20 == -1;
          }
        }
        if (bVar43 != 0) {
          operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
        }
        pbVar34 = pbStack_1f0;
        pbVar50 = pbStack_1f0;
        if (!bVar18) goto LAB_0027a0e2;
        pbVar49 = local_1f8 + 0x18;
        pbVar50 = local_1f8;
        pbVar51 = local_1f8;
        if (pbVar49 == pbStack_1f0) {
LAB_0027a3ec:
          do {
            pbVar34 = pbVar49 + -0x18;
            if ((pbVar49[-0x18] & 1) != 0) {
              operator_delete(*(void **)(pbVar49 + -8));
            }
            pbVar49 = pbVar34;
          } while (pbVar34 != pbVar50);
        }
        else {
          do {
            if ((*pbVar51 & 1) != 0) {
              operator_delete(*(void **)(pbVar51 + 0x10));
            }
            pbVar50 = pbVar51 + 0x18;
            *(undefined8 *)(pbVar51 + 0x10) = *(undefined8 *)(pbVar51 + 0x28);
            *(undefined8 *)pbVar51 = *(undefined8 *)(pbVar51 + 0x18);
            *(undefined8 *)(pbVar51 + 8) = *(undefined8 *)(pbVar51 + 0x20);
            pbVar51[0x18] = 0;
            pbVar51[0x19] = 0;
            pbVar49 = pbVar51 + 0x30;
            pbVar51 = pbVar50;
          } while (pbVar49 != pbVar34);
          pbVar49 = pbStack_1f0;
          if (pbVar50 != pbStack_1f0) goto LAB_0027a3ec;
        }
        pbStack_1f0 = pbVar50;
        pbVar34 = pbVar50;
        if (local_1f8 != pbVar50) goto LAB_0027a0ef;
      }
      pbStack_1f0 = pbVar34;
      local_330 = _navdata_;
      pbVar34 = pbStack_1f0;
      if ((1 < (ulong)(((long)pbVar50 - (long)local_1f8 >> 3) * -0x5555555555555555)) &&
         (pbVar49 = local_1f8, pbVar51 = local_1f8, local_1f8 != pbVar50 + -0x18)) {
LAB_0027a2e0:
        pbVar50 = pbVar51 + 0x18;
        if ((*pbVar51 & 1) == 0) {
          if (*pbVar51 >> 1 == 2) goto LAB_0027a30d;
LAB_0027a2c0:
          pbVar49 = pbVar49 + 0x18;
          pbVar51 = pbVar50;
          pbVar34 = pbStack_1f0;
          if (pbVar50 == pbStack_1f0 + -0x18) goto LAB_0027a50d;
          goto LAB_0027a2e0;
        }
        if (*(long *)(pbVar51 + 8) != 2) goto LAB_0027a2c0;
LAB_0027a30d:
        iVar20 = std::string::compare((ulong)pbVar51,0,(char *)0xffffffffffffffff,0x27cec3c);
        if (iVar20 != 0) goto LAB_0027a2c0;
        uVar25 = (ulong)(*pbVar50 >> 1);
        bVar43 = *pbVar50 & 1;
        uVar53 = *(ulong *)(pbVar51 + 0x20);
        uVar62 = uVar53;
        if (bVar43 == 0) {
          uVar62 = uVar25;
        }
        if (uVar62 == 4) {
          iVar20 = std::string::compare((ulong)pbVar50,0,(char *)0xffffffffffffffff,0x27832e8);
          if (iVar20 != 0) {
            uVar53 = *(ulong *)(pbVar51 + 0x20);
            bVar43 = *pbVar50 & 1;
            uVar25 = (ulong)(*pbVar50 >> 1);
            goto LAB_0027a379;
          }
        }
        else {
LAB_0027a379:
          if (bVar43 != 0) {
            uVar25 = uVar53;
          }
          if ((uVar25 != 3) ||
             (iVar20 = std::string::compare((ulong)pbVar50,0,(char *)0xffffffffffffffff,0x27832e4),
             iVar20 != 0)) goto LAB_0027a2c0;
        }
        pbVar34 = pbStack_1f0;
        local_1d8[0xa4] = (ATCAircraftFlightPlan)0x1;
        pbVar51 = pbVar49 + 0x18;
        pbVar52 = pbVar49;
        pbVar50 = pbVar49;
        if (pbVar49 + 0x18 == pbStack_1f0) goto LAB_0027a498;
        do {
          if ((*pbVar52 & 1) != 0) {
            operator_delete(*(void **)(pbVar52 + 0x10));
          }
          pbVar50 = pbVar52 + 0x18;
          *(undefined8 *)(pbVar52 + 0x10) = *(undefined8 *)(pbVar52 + 0x28);
          *(undefined8 *)pbVar52 = *(undefined8 *)(pbVar52 + 0x18);
          *(undefined8 *)(pbVar52 + 8) = *(undefined8 *)(pbVar52 + 0x20);
          pbVar52[0x18] = 0;
          pbVar52[0x19] = 0;
          pbVar51 = pbVar52 + 0x30;
          pbVar52 = pbVar50;
        } while (pbVar51 != pbVar34);
        pbVar51 = pbStack_1f0;
        if (pbVar50 != pbStack_1f0) {
LAB_0027a498:
          do {
            pbVar34 = pbVar51 + -0x18;
            if ((pbVar51[-0x18] & 1) != 0) {
              operator_delete(*(void **)(pbVar51 + -8));
            }
            pbVar51 = pbVar34;
          } while (pbVar34 != pbVar50);
        }
        pbVar34 = pbVar49;
        pbStack_1f0 = pbVar50;
        if (pbVar49 + 0x18 != pbVar50) {
          do {
            if ((*pbVar34 & 1) != 0) {
              operator_delete(*(void **)(pbVar34 + 0x10));
            }
            pbVar49 = pbVar34 + 0x18;
            *(undefined8 *)(pbVar34 + 0x10) = *(undefined8 *)(pbVar34 + 0x28);
            *(undefined8 *)pbVar34 = *(undefined8 *)(pbVar34 + 0x18);
            *(undefined8 *)(pbVar34 + 8) = *(undefined8 *)(pbVar34 + 0x20);
            pbVar34[0x18] = 0;
            pbVar34[0x19] = 0;
            pbVar51 = pbVar34 + 0x30;
            pbVar34 = pbVar49;
          } while (pbVar51 != pbVar50);
          pbVar50 = pbStack_1f0;
          if (pbVar49 == pbStack_1f0) goto LAB_0027a50d;
        }
        do {
          pbVar51 = pbVar50 + -0x18;
          if ((pbVar50[-0x18] & 1) != 0) {
            operator_delete(*(void **)(pbVar50 + -8));
          }
          pbVar50 = pbVar51;
          pbVar34 = pbVar49;
        } while (pbVar51 != pbVar49);
      }
LAB_0027a50d:
      pbStack_1f0 = pbVar34;
      local_2c0 = (string *)(local_1d8 + 0x50);
      local_298 = (string *)(local_1d8 + 0x70);
      local_2a8 = (string *)(local_1d8 + 0x88);
      plVar66 = local_200;
      if (pbStack_1f0 != local_1f8) {
        local_258 = local_220 + 2;
        local_390 = local_220 + 1;
        local_3a0 = (start_loc_spec *)&DAT_03c9af10;
        local_328 = local_1d8 + 0x52;
        local_398 = local_1d8 + 0x8a;
        uVar53 = 0;
        local_218 = (awy_node_struct *)0x0;
        local_208 = 0;
        do {
          if ((local_1f8[uVar53 * 0x18] & 1) == 0) {
            if (local_1f8[uVar53 * 0x18] >> 1 != 0) {
LAB_0027a67a:
              local_210 = uVar53 * 3;
              if ((((int)local_208 == 0) &&
                  (cVar17 = ATCUtilsAcfIsFlying(local_278), cVar17 == '\0')) &&
                 (local_2b0 != (vec_apt_struct *)0x0)) {
                if ((local_1f8[local_210 * 8] & 1) == 0) {
                  if (local_1f8[local_210 * 8] >> 1 == 3) goto LAB_0027aa2c;
                }
                else if (*(long *)(local_1f8 + local_210 * 8 + 8) == 3) {
LAB_0027aa2c:
                  iVar20 = std::string::compare
                                     ((ulong)(local_1f8 + local_210 * 8),0,
                                      (char *)0xffffffffffffffff,0x27cec3f);
                  if (iVar20 == 0) {
                    local_208 = 0;
                    std::string::assign((char *)local_298);
                    goto LAB_0027a610;
                  }
                }
                _local_e8 = (undefined1  [16])0x0;
                local_d8 = (char *)0x0;
                local_2a0 = uVar53;
                pcVar56 = (char *)vec_apt_struct::get_id_for_navdata(local_2b0);
                sVar26 = _strlen(pcVar56);
                if (0xffffffffffffffef < sVar26) {
                    /* WARNING: Subroutine does not return */
                  std::string::__throw_length_error();
                }
                if (sVar26 < 0x17) {
                  local_c8 = (ATCAircraft)((char)SUB81(sVar26,0) * '\x02');
                  puVar31 = &uStack_c7;
                  if (sVar26 != 0) goto LAB_0027b457;
                }
                else {
                  uVar53 = sVar26 + 0x10 & 0xfffffffffffffff0;
                  puVar31 = operator_new(uVar53);
                  local_b8 = SUB81(puVar31,0);
                  uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                  uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                  local_c8 = (ATCAircraft)((byte)uVar53 | 1);
                  uStack_c7 = (uint)(uVar53 >> 8);
                  cStack_c3 = (char)(uVar53 >> 0x28);
                  cStack_c2 = (char)(uVar53 >> 0x30);
                  cStack_c1 = (char)(uVar53 >> 0x38);
                  uStack_bf = (undefined7)(sVar26 >> 8);
                  AStack_c0 = SUB81(sVar26,0);
LAB_0027b457:
                  _memcpy(puVar31,pcVar56,sVar26);
                }
                *(undefined1 *)((long)puVar31 + sVar26) = 0;
                AIRNAV5::Database::NavDataBase::
                getProcs<AIRNAV5::Navigation::StandardRoute<(AIRNAV5::Navigation::StandardRouteType)0>>
                          (local_330,(vector *)&local_c8,SUB81(local_e8,0));
                lVar67 = local_210;
                if (((byte)local_c8 & 1) != 0) {
                  operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                }
                local_128 = (undefined1  [16])0x0;
                local_118 = 0;
                local_110 = (undefined1  [16])0x0;
                local_100 = '\0';
                local_f8 = 0;
                local_f0 = 0;
                _local_158 = (undefined1  [16])0x0;
                local_148 = (char *)0x0;
                uStack_140._0_1_ = 0;
                uStack_140._1_7_ = 0;
                local_138._0_9_ = SUB169((undefined1  [16])0x0,7);
                this_02 = stack0xffffffffffffff20;
                std::string::string(&local_170,(string *)(local_1f8 + lVar67 * 8));
                if (((byte)local_170 & 1) == 0) {
                  uVar53 = (ulong)((byte)local_170 >> 1);
                  puVar71 = &uStack_16f;
                }
                else {
                  uVar53 = CONCAT26(uStack_162,local_168);
                  puVar71 = local_160;
                }
                local_98 = (undefined1  [16])0x0;
                local_88 = local_88 & 0xffffffffffffff00;
                local_80 = (undefined1  [16])0x0;
                local_70 = local_70 & 0xffffffffffffff00;
                local_68 = 0;
                local_60 = 0;
                local_c8 = (ATCAircraft)0x0;
                uStack_c7 = 0;
                cStack_c3 = '\0';
                cStack_c2 = '\0';
                cStack_c1 = '\0';
                AStack_c0 = (ATCAircraft)0x0;
                uStack_bf = 0;
                local_b8 = (ATCAircraft)0x0;
                uStack_b7 = 0;
                uStack_b6 = 0;
                uStack_b0 = 0;
                uStack_af = 0;
                local_a8 = (function *)0x0;
                uStack_a0 = 0;
                local_228 = (void *)(lVar67 * 8);
                bVar18 = std::regex::__search<std::allocator<std::sub_match<char_const*>>>
                                   ((regex *)&ATCFlightRoute::reSID,puVar71,uVar53 + (long)puVar71,
                                    &local_c8,0x1040);
                std::
                match_results<std::__wrap_iter<char_const*>,std::allocator<std::sub_match<std::__wrap_iter<char_const*>>>>
                ::__assign<char_const*,std::allocator<std::sub_match<char_const*>>>
                          ((match_results<std::__wrap_iter<char_const*>,std::allocator<std::sub_match<std::__wrap_iter<char_const*>>>>
                            *)local_158,puVar71,uVar53 + (long)puVar71,&local_c8,0);
                pvVar24 = (void *)CONCAT17(cStack_c1,
                                           CONCAT16(cStack_c2,
                                                    CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))
                                                   ));
                if (pvVar24 != (void *)0x0) {
                  AStack_c0 = local_c8;
                  uStack_bf = (undefined7)((ulong)pvVar24 >> 8);
                  operator_delete(pvVar24);
                }
                plVar66 = local_200;
                if (bVar18) {
                  if (local_100 == '\0') {
                    pRVar13 = stack0xffffffffffffff20;
                    pauVar33 = (undefined1 (*) [16])(local_158._0_8_ + 0x30);
                    if ((ulong)((stack0xfffffffffffffeb0 - local_158._0_8_ >> 3) *
                               -0x5555555555555555) < 3) {
                      pauVar33 = (undefined1 (*) [16])&uStack_140;
                    }
                    local_178 = pauVar33[1][0];
                    local_188 = *(undefined8 *)*pauVar33;
                    uStack_180 = *(undefined8 *)(*pauVar33 + 8);
                    local_58 = *pauVar33;
                    local_48 = (undefined1 *)CONCAT71(uStack_177,pauVar33[1][0]);
                    this_02 = (Route *)local_e8._0_8_;
                    for (pRVar72 = (Route *)local_e8._0_8_; pRVar72 != pRVar13;
                        pRVar72 = pRVar72 + 0x90) {
                      AIRNAV5::Navigation::Procedure::name();
                      bVar18 = std::operator==((basic_string *)&local_c8,(sub_match *)local_58);
                      if (((byte)local_c8 & 1) != 0) {
                        operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                      }
                      this_02 = pRVar72;
                      if (bVar18) break;
                      this_02 = pRVar13;
                    }
                  }
                  else {
                    stack0xfffffffffffffeb0 = local_158._0_8_;
                  }
                }
                if (this_02 == stack0xffffffffffffff20) {
LAB_0027d47e:
                  iVar20 = 0;
                  if (((byte)local_170 & 1) != 0) goto LAB_0027d48a;
LAB_0027d4ad:
                }
                else {
                  local_58 = (undefined1  [16])0x0;
                  auVar78 = **(undefined1 (**) [16])(local_290 + 0x10);
                  local_1c8._0_8_ = auVar78._8_8_;
                  local_1c8._8_4_ = auVar78._0_4_;
                  local_1c8._12_4_ = auVar78._4_4_;
                  local_c8 = (ATCAircraft)0x0;
                  uStack_c7 = uStack_c7 & 0xffffff00;
                  pAVar54 = local_278;
                  ATCRouteUtils::FindSIDForRoute
                            ((ATCRouteUtils *)&local_198,local_278,local_2b0,local_58,
                             (GeoPoint2D *)local_1c8,(string *)&local_c8,
                             (string *)((long)local_228 + (long)local_1f8));
                  dev = (dev_t)pAVar54;
                  iVar20 = extraout_EDX;
                  if (((byte)local_c8 & 1) != 0) {
                    operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                    iVar20 = extraout_EDX_00;
                  }
                  if ((ATCNamedTransition *)CONCAT26(uStack_192,local_198) ==
                      (ATCNamedTransition *)0x0) {
                    local_a8 = (function *)0x0;
                    uStack_a0 = 0;
                    uStack_9f = 0;
                    local_b8 = (ATCAircraft)0x0;
                    uStack_b7 = 0;
                    uStack_b6 = 0;
                    uStack_b0 = 0;
                    uStack_af = 0;
                    local_c8 = (ATCAircraft)0x0;
                    uStack_c7 = 0;
                    cStack_c3 = '\0';
                    cStack_c2 = '\0';
                    cStack_c1 = '\0';
                    AStack_c0 = (ATCAircraft)0x0;
                    uStack_bf = 0;
                    local_80 = ZEXT816(0);
                    local_98._8_8_ = 0;
                    local_88 = 0;
                    local_70 = 0;
                    iVar20 = AIRNAV5::Navigation::Route::clone(this_02,dev,iVar20);
                    if (CONCAT44(extraout_var,iVar20) == 0) {
                      uVar32 = 0;
                    }
                    else {
                      uVar32 = ___dynamic_cast(CONCAT44(extraout_var,iVar20),
                                               &AIRNAV5::Navigation::Route::typeinfo,
                                               &AIRNAV5::Navigation::Procedure::typeinfo,0);
                    }
                    puVar38 = operator_new(0x20);
                    puVar38[1] = 0;
                    puVar38[2] = 0;
                    *puVar38 = &PTR____shared_ptr_pointer_02ad12a0;
                    puVar38[3] = uVar32;
                    local_b8 = SUB81(uVar32,0);
                    uStack_b7 = (undefined1)((ulong)uVar32 >> 8);
                    uStack_b6 = (undefined6)((ulong)uVar32 >> 0x10);
                    plVar66 = (long *)CONCAT71(uStack_af,uStack_b0);
                    uStack_b0 = SUB81(puVar38,0);
                    uStack_af = (undefined7)((ulong)puVar38 >> 8);
                    if (plVar66 != (long *)0x0) {
                      LOCK();
                      plVar6 = plVar66 + 1;
                      lVar67 = *plVar6;
                      *plVar6 = *plVar6 + -1;
                      UNLOCK();
                      if (lVar67 == 0) {
                        (**(code **)(*plVar66 + 0x10))(plVar66);
                        std::__shared_weak_count::__release_weak();
                      }
                    }
                    ATCNamedTransition::GetLastKnownPoint
                              ((ATCNamedTransition *)&local_c8,(GeoPoint2D *)local_248);
                    ATCNamedTransition::~ATCNamedTransition((ATCNamedTransition *)&local_c8);
LAB_0027c703:
                    uVar53 = (stack0xfffffffffffffeb0 - local_158._0_8_ >> 3) * -0x5555555555555555;
                    pcVar56 = (char *)(local_158._0_8_ + 0x40);
                    if (uVar53 < 3) {
                      pcVar56 = local_138 + 8;
                    }
                    if (*pcVar56 == '\0') {
                      local_c8 = (ATCAircraft)0x0;
                      uStack_c7 = 0;
                      cStack_c3 = '\0';
                      cStack_c2 = '\0';
                      cStack_c1 = '\0';
                      AStack_c0 = (ATCAircraft)0x0;
                      uStack_bf = 0;
                      local_b8 = (ATCAircraft)0x0;
                      uStack_b7 = 0;
                      uStack_b6 = 0;
                    }
                    else {
                      puVar39 = (undefined8 *)(local_158._0_8_ + 0x38);
                      puVar38 = (undefined8 *)(local_158._0_8_ + 0x30);
                      if (uVar53 < 3) {
                        puVar39 = (undefined8 *)local_138;
                        puVar38 = &uStack_140;
                      }
                      puVar55 = (undefined1 *)*puVar38;
                      puVar61 = (undefined1 *)*puVar39;
                      uVar53 = (long)puVar61 - (long)puVar55;
                      if (0xffffffffffffffef < uVar53) {
                    /* WARNING: Subroutine does not return */
                        std::string::__throw_length_error();
                      }
                      if (uVar53 < 0x17) {
                        local_c8 = (ATCAircraft)((char)SUB81(uVar53,0) * '\x02');
                        puVar31 = &uStack_c7;
                      }
                      else {
                        uVar25 = uVar53 + 0x10 & 0xfffffffffffffff0;
                        puVar31 = operator_new(uVar25);
                        local_b8 = SUB81(puVar31,0);
                        uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                        uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                        local_c8 = (ATCAircraft)((byte)uVar25 | 1);
                        uStack_c7 = (uint)(uVar25 >> 8);
                        cStack_c3 = (char)(uVar25 >> 0x28);
                        cStack_c2 = (char)(uVar25 >> 0x30);
                        cStack_c1 = (char)(uVar25 >> 0x38);
                        uStack_bf = (undefined7)(uVar53 >> 8);
                        AStack_c0 = SUB81(uVar53,0);
                      }
                      if (puVar55 != puVar61) {
                        if ((0x1f < uVar53) &&
                           ((puVar55 + uVar53 <= puVar31 ||
                            ((undefined1 *)((long)puVar31 + uVar53) <= puVar55)))) {
                          uVar64 = uVar53 & 0xffffffffffffffe0;
                          uVar62 = (uVar64 - 0x20 >> 5) + 1;
                          uVar25 = (ulong)((uint)uVar62 & 3);
                          if (uVar64 - 0x20 < 0x60) {
                            lVar46 = 0;
                          }
                          else {
                            lVar67 = -(uVar62 & 0xfffffffffffffffc);
                            lVar46 = 0;
                            do {
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar46) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x10);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x10) + 8);
                              *(undefined8 *)((long)puVar31 + lVar46) =
                                   *(undefined8 *)(puVar55 + lVar46);
                              ((undefined8 *)((long)puVar31 + lVar46))[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x10);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x20) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x30);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x30) + 8);
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x20);
                              *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x20);
                              puVar38[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x30);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x40) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x50);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x50) + 8);
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x40);
                              *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x40);
                              puVar38[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x50);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x60) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x70);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x70) + 8);
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x60);
                              *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x60);
                              puVar38[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x70);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              lVar46 = lVar46 + 0x80;
                              lVar67 = lVar67 + 4;
                            } while (lVar67 != 0);
                          }
                          if (uVar25 != 0) {
                            lVar67 = 0;
                            do {
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar67 + lVar46) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar67 + lVar46 + 0x10);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar67 + lVar46 + 0x10) + 8);
                              puVar38 = (undefined8 *)((long)puVar31 + lVar67 + lVar46);
                              *puVar38 = *(undefined8 *)(puVar55 + lVar67 + lVar46);
                              puVar38[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar67 + lVar46 + 0x10);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              lVar67 = lVar67 + 0x20;
                            } while (uVar25 << 5 != lVar67);
                          }
                          puVar31 = (uint *)((long)puVar31 + uVar64);
                          if (uVar53 == uVar64) goto LAB_0027cc53;
                          puVar55 = puVar55 + uVar64;
                        }
                        uVar21 = (int)puVar61 - (int)puVar55;
                        uVar25 = ~(ulong)puVar55;
                        uVar53 = (ulong)uVar21 & 7;
                        if ((uVar21 & 7) != 0) {
                          do {
                            *(undefined1 *)puVar31 = *puVar55;
                            puVar55 = puVar55 + 1;
                            puVar31 = (uint *)((long)puVar31 + 1);
                            uVar53 = uVar53 - 1;
                          } while (uVar53 != 0);
                        }
                        if ((undefined1 *)0x6 < puVar61 + uVar25) {
                          do {
                            *(undefined1 *)puVar31 = *puVar55;
                            *(undefined1 *)((long)puVar31 + 1) = puVar55[1];
                            *(undefined1 *)((long)puVar31 + 2) = puVar55[2];
                            *(undefined1 *)((long)puVar31 + 3) = puVar55[3];
                            *(undefined1 *)(puVar31 + 1) = puVar55[4];
                            *(undefined1 *)((long)puVar31 + 5) = puVar55[5];
                            *(undefined1 *)((long)puVar31 + 6) = puVar55[6];
                            *(undefined1 *)((long)puVar31 + 7) = puVar55[7];
                            puVar31 = puVar31 + 2;
                            puVar55 = puVar55 + 8;
                          } while (puVar55 != puVar61);
                        }
                      }
LAB_0027cc53:
                      *(undefined1 *)puVar31 = 0;
                    }
                    if (((byte)*local_298 & 1) != 0) {
                      operator_delete(*(void **)(local_1d8 + 0x80));
                    }
                    *(ulong *)(local_298 + 0x10) = CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
                    *(ulong *)local_298 =
                         CONCAT17(cStack_c1,
                                  CONCAT16(cStack_c2,
                                           CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))));
                    *(ulong *)(local_298 + 8) = CONCAT71(uStack_bf,AStack_c0);
                    uVar53 = (stack0xfffffffffffffeb0 - local_158._0_8_ >> 3) * -0x5555555555555555;
                    pcVar56 = (char *)(local_158._0_8_ + 0x58);
                    if (uVar53 < 4) {
                      pcVar56 = local_138 + 8;
                    }
                    if (*pcVar56 == '\0') {
                      if ((*local_1f8 & 1) == 0) {
                        local_1f8[0] = 0;
                        local_1f8[1] = 0;
                      }
                      else {
                        **(undefined1 **)(local_1f8 + 0x10) = 0;
                        local_1f8[8] = 0;
                        local_1f8[9] = 0;
                        local_1f8[10] = 0;
                        local_1f8[0xb] = 0;
                        local_1f8[0xc] = 0;
                        local_1f8[0xd] = 0;
                        local_1f8[0xe] = 0;
                        local_1f8[0xf] = 0;
                      }
                    }
                    else {
                      puVar39 = (undefined8 *)(local_158._0_8_ + 0x50);
                      puVar38 = (undefined8 *)(local_158._0_8_ + 0x48);
                      if (uVar53 < 4) {
                        puVar39 = (undefined8 *)local_138;
                        puVar38 = &uStack_140;
                      }
                      puVar55 = (undefined1 *)*puVar38;
                      puVar61 = (undefined1 *)*puVar39;
                      uVar53 = (long)puVar61 - (long)puVar55;
                      if (0xffffffffffffffef < uVar53) {
                    /* WARNING: Subroutine does not return */
                        std::string::__throw_length_error();
                      }
                      if (uVar53 < 0x17) {
                        local_c8 = (ATCAircraft)((char)SUB81(uVar53,0) * '\x02');
                        puVar31 = &uStack_c7;
                      }
                      else {
                        uVar25 = uVar53 + 0x10 & 0xfffffffffffffff0;
                        puVar31 = operator_new(uVar25);
                        local_b8 = SUB81(puVar31,0);
                        uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                        uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                        local_c8 = (ATCAircraft)((byte)uVar25 | 1);
                        uStack_c7 = (uint)(uVar25 >> 8);
                        cStack_c3 = (char)(uVar25 >> 0x28);
                        cStack_c2 = (char)(uVar25 >> 0x30);
                        cStack_c1 = (char)(uVar25 >> 0x38);
                        uStack_bf = (undefined7)(uVar53 >> 8);
                        AStack_c0 = SUB81(uVar53,0);
                      }
                      pbVar50 = local_1f8;
                      if (puVar55 != puVar61) {
                        if ((0x1f < uVar53) &&
                           ((puVar55 + uVar53 <= puVar31 ||
                            ((undefined1 *)((long)puVar31 + uVar53) <= puVar55)))) {
                          uVar64 = uVar53 & 0xffffffffffffffe0;
                          uVar62 = (uVar64 - 0x20 >> 5) + 1;
                          uVar25 = (ulong)((uint)uVar62 & 3);
                          if (uVar64 - 0x20 < 0x60) {
                            lVar46 = 0;
                          }
                          else {
                            lVar67 = -(uVar62 & 0xfffffffffffffffc);
                            lVar46 = 0;
                            do {
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar46) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x10);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x10) + 8);
                              *(undefined8 *)((long)puVar31 + lVar46) =
                                   *(undefined8 *)(puVar55 + lVar46);
                              ((undefined8 *)((long)puVar31 + lVar46))[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x10);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x20) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x30);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x30) + 8);
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x20);
                              *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x20);
                              puVar38[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x30);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x40) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x50);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x50) + 8);
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x40);
                              *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x40);
                              puVar38[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x50);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x60) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x70);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x70) + 8);
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x60);
                              *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x60);
                              puVar38[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x70);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              lVar46 = lVar46 + 0x80;
                              lVar67 = lVar67 + 4;
                            } while (lVar67 != 0);
                          }
                          if (uVar25 != 0) {
                            lVar67 = 0;
                            do {
                              uVar32 = *(undefined8 *)((long)(puVar55 + lVar67 + lVar46) + 8);
                              uVar4 = *(undefined8 *)(puVar55 + lVar67 + lVar46 + 0x10);
                              uVar5 = *(undefined8 *)((long)(puVar55 + lVar67 + lVar46 + 0x10) + 8);
                              puVar38 = (undefined8 *)((long)puVar31 + lVar67 + lVar46);
                              *puVar38 = *(undefined8 *)(puVar55 + lVar67 + lVar46);
                              puVar38[1] = uVar32;
                              puVar38 = (undefined8 *)((long)puVar31 + lVar67 + lVar46 + 0x10);
                              *puVar38 = uVar4;
                              puVar38[1] = uVar5;
                              lVar67 = lVar67 + 0x20;
                            } while (uVar25 << 5 != lVar67);
                          }
                          puVar31 = (uint *)((long)puVar31 + uVar64);
                          if (uVar53 == uVar64) goto LAB_0027cee3;
                          puVar55 = puVar55 + uVar64;
                        }
                        uVar21 = (int)puVar61 - (int)puVar55;
                        uVar25 = ~(ulong)puVar55;
                        uVar53 = (ulong)uVar21 & 7;
                        if ((uVar21 & 7) != 0) {
                          do {
                            *(undefined1 *)puVar31 = *puVar55;
                            puVar55 = puVar55 + 1;
                            puVar31 = (uint *)((long)puVar31 + 1);
                            uVar53 = uVar53 - 1;
                          } while (uVar53 != 0);
                        }
                        if ((undefined1 *)0x6 < puVar61 + uVar25) {
                          do {
                            *(undefined1 *)puVar31 = *puVar55;
                            *(undefined1 *)((long)puVar31 + 1) = puVar55[1];
                            *(undefined1 *)((long)puVar31 + 2) = puVar55[2];
                            *(undefined1 *)((long)puVar31 + 3) = puVar55[3];
                            *(undefined1 *)(puVar31 + 1) = puVar55[4];
                            *(undefined1 *)((long)puVar31 + 5) = puVar55[5];
                            *(undefined1 *)((long)puVar31 + 6) = puVar55[6];
                            *(undefined1 *)((long)puVar31 + 7) = puVar55[7];
                            puVar31 = puVar31 + 2;
                            puVar55 = puVar55 + 8;
                          } while (puVar55 != puVar61);
                        }
                      }
LAB_0027cee3:
                      *(undefined1 *)puVar31 = 0;
                      if ((*local_1f8 & 1) != 0) {
                        operator_delete(*(void **)(local_1f8 + 0x10));
                      }
                      *(ulong *)(pbVar50 + 0x10) = CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
                      *(ulong *)pbVar50 =
                           CONCAT17(cStack_c1,
                                    CONCAT16(cStack_c2,
                                             CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))));
                      *(ulong *)(pbVar50 + 8) = CONCAT71(uStack_bf,AStack_c0);
                      uVar53 = (stack0xfffffffffffffeb0 - local_158._0_8_ >> 3) *
                               -0x5555555555555555;
                      pcVar56 = (char *)(local_158._0_8_ + 0x58);
                      if (uVar53 < 4) {
                        pcVar56 = local_138 + 8;
                      }
                      if (*pcVar56 == '\0') {
                        local_58 = ZEXT816(0);
                        local_48 = (undefined1 *)0x0;
                      }
                      else {
                        puVar39 = (undefined8 *)(local_158._0_8_ + 0x50);
                        puVar38 = (undefined8 *)(local_158._0_8_ + 0x48);
                        if (uVar53 < 4) {
                          puVar39 = (undefined8 *)local_138;
                          puVar38 = &uStack_140;
                        }
                        puVar55 = (undefined1 *)*puVar38;
                        puVar61 = (undefined1 *)*puVar39;
                        uVar53 = (long)puVar61 - (long)puVar55;
                        if (0xffffffffffffffef < uVar53) {
                    /* WARNING: Subroutine does not return */
                          std::string::__throw_length_error();
                        }
                        if (uVar53 < 0x17) {
                          local_58[0] = (sub_match)((char)uVar53 * '\x02');
                          puVar40 = local_58 + 1;
                        }
                        else {
                          uVar25 = uVar53 + 0x10 & 0xfffffffffffffff0;
                          puVar40 = operator_new(uVar25);
                          local_58._8_8_ = uVar53;
                          local_58._0_8_ = uVar25 | 1;
                          local_48 = puVar40;
                        }
                        if (puVar55 != puVar61) {
                          if ((0x1f < uVar53) &&
                             ((puVar55 + uVar53 <= puVar40 || (puVar40 + uVar53 <= puVar55)))) {
                            uVar64 = uVar53 & 0xffffffffffffffe0;
                            uVar62 = (uVar64 - 0x20 >> 5) + 1;
                            uVar25 = (ulong)((uint)uVar62 & 3);
                            if (uVar64 - 0x20 < 0x60) {
                              lVar46 = 0;
                            }
                            else {
                              lVar67 = -(uVar62 & 0xfffffffffffffffc);
                              lVar46 = 0;
                              do {
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x10);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x10) + 8);
                                *(undefined8 *)(puVar40 + lVar46) =
                                     *(undefined8 *)(puVar55 + lVar46);
                                *(undefined8 *)((long)(puVar40 + lVar46) + 8) = uVar32;
                                *(undefined8 *)(puVar40 + lVar46 + 0x10) = uVar4;
                                *(undefined8 *)((long)(puVar40 + lVar46 + 0x10) + 8) = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x20) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x30);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x30) + 8);
                                *(undefined8 *)(puVar40 + lVar46 + 0x20) =
                                     *(undefined8 *)(puVar55 + lVar46 + 0x20);
                                *(undefined8 *)((long)(puVar40 + lVar46 + 0x20) + 8) = uVar32;
                                *(undefined8 *)(puVar40 + lVar46 + 0x30) = uVar4;
                                *(undefined8 *)((long)(puVar40 + lVar46 + 0x30) + 8) = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x40) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x50);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x50) + 8);
                                *(undefined8 *)(puVar40 + lVar46 + 0x40) =
                                     *(undefined8 *)(puVar55 + lVar46 + 0x40);
                                *(undefined8 *)((long)(puVar40 + lVar46 + 0x40) + 8) = uVar32;
                                *(undefined8 *)(puVar40 + lVar46 + 0x50) = uVar4;
                                *(undefined8 *)((long)(puVar40 + lVar46 + 0x50) + 8) = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x60) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x70);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x70) + 8);
                                *(undefined8 *)(puVar40 + lVar46 + 0x60) =
                                     *(undefined8 *)(puVar55 + lVar46 + 0x60);
                                *(undefined8 *)((long)(puVar40 + lVar46 + 0x60) + 8) = uVar32;
                                *(undefined8 *)(puVar40 + lVar46 + 0x70) = uVar4;
                                *(undefined8 *)((long)(puVar40 + lVar46 + 0x70) + 8) = uVar5;
                                lVar46 = lVar46 + 0x80;
                                lVar67 = lVar67 + 4;
                              } while (lVar67 != 0);
                            }
                            if (uVar25 != 0) {
                              lVar67 = 0;
                              do {
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar67 + lVar46) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar67 + lVar46 + 0x10);
                                uVar5 = *(undefined8 *)
                                         ((long)(puVar55 + lVar67 + lVar46 + 0x10) + 8);
                                *(undefined8 *)(puVar40 + lVar67 + lVar46) =
                                     *(undefined8 *)(puVar55 + lVar67 + lVar46);
                                *(undefined8 *)((long)(puVar40 + lVar67 + lVar46) + 8) = uVar32;
                                *(undefined8 *)(puVar40 + lVar67 + lVar46 + 0x10) = uVar4;
                                *(undefined8 *)((long)(puVar40 + lVar67 + lVar46 + 0x10) + 8) =
                                     uVar5;
                                lVar67 = lVar67 + 0x20;
                              } while (uVar25 << 5 != lVar67);
                            }
                            puVar40 = puVar40 + uVar64;
                            if (uVar53 == uVar64) goto LAB_0027d133;
                            puVar55 = puVar55 + uVar64;
                          }
                          uVar21 = (int)puVar61 - (int)puVar55;
                          uVar25 = ~(ulong)puVar55;
                          uVar53 = (ulong)uVar21 & 7;
                          if ((uVar21 & 7) != 0) {
                            do {
                              *puVar40 = *puVar55;
                              puVar55 = puVar55 + 1;
                              puVar40 = puVar40 + 1;
                              uVar53 = uVar53 - 1;
                            } while (uVar53 != 0);
                          }
                          if ((undefined1 *)0x6 < puVar61 + uVar25) {
                            do {
                              *puVar40 = *puVar55;
                              puVar40[1] = puVar55[1];
                              puVar40[2] = puVar55[2];
                              puVar40[3] = puVar55[3];
                              puVar40[4] = puVar55[4];
                              puVar40[5] = puVar55[5];
                              puVar40[6] = puVar55[6];
                              puVar40[7] = puVar55[7];
                              puVar40 = puVar40 + 8;
                              puVar55 = puVar55 + 8;
                            } while (puVar55 != puVar61);
                          }
                        }
LAB_0027d133:
                        *puVar40 = 0;
                      }
                      puVar41 = (ulong *)std::string::insert((ulong)local_58,(char *)0x0);
                      puVar31 = (uint *)puVar41[2];
                      local_b8 = SUB81(puVar31,0);
                      uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                      uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                      uVar53 = *puVar41;
                      local_c8 = SUB81(uVar53,0);
                      uStack_c7 = (uint)(uVar53 >> 8);
                      cStack_c3 = (char)(uVar53 >> 0x28);
                      cStack_c2 = (char)(uVar53 >> 0x30);
                      cStack_c1 = (char)(uVar53 >> 0x38);
                      AStack_c0 = SUB81(puVar41[1],0);
                      uStack_bf = (undefined7)(puVar41[1] >> 8);
                      *puVar41 = 0;
                      puVar41[1] = 0;
                      puVar41[2] = 0;
                      if ((uVar53 & 1) == 0) {
                        puVar31 = &uStack_c7;
                      }
                      std::string::append((char *)local_298,(ulong)puVar31);
                      if (((byte)local_c8 & 1) != 0) {
                        operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                      }
                      if (((byte)local_58[0] & 1) != 0) {
                        operator_delete(local_48);
                      }
                    }
                    local_308 = (ATCAircraftFlightPlan)0x0;
                    AStack_307 = (ATCAircraftFlightPlan)0x0;
                    uStack_306 = 0;
                    uStack_300 = 0;
                    uStack_2fe = 0;
                    local_2f8 = (void *)0x0;
                    local_1d0 = pbStack_1f0;
                    pvVar24 = (void *)0x0;
                    if (local_1f8 == pbStack_1f0) {
                      AVar69 = (ATCAircraftFlightPlan)0x0;
                      AVar65 = (ATCAircraftFlightPlan)0x0;
                    }
                    else {
                      pvVar68 = (void *)0x0;
                      pbVar50 = local_1f8;
                      do {
                        pvVar12 = local_2f8;
                        std::operator+((string *)&local_c8,(char *)&local_308);
                        pbVar34 = pbVar50 + 1;
                        if ((*pbVar50 & 1) != 0) {
                          pbVar34 = *(byte **)(pbVar50 + 0x10);
                        }
                        pbVar34 = (byte *)std::string::append((char *)&local_c8,(ulong)pbVar34);
                        local_228 = (void *)(ulong)*pbVar34;
                        AVar69 = *(ATCAircraftFlightPlan *)(pbVar34 + 1);
                        local_58._8_8_ =
                             (undefined8)
                             (CONCAT28(local_58._14_2_,*(undefined8 *)(pbVar34 + 8)) >> 0x10);
                        local_58._0_8_ = *(undefined8 *)(pbVar34 + 2);
                        pvVar24 = *(void **)(pbVar34 + 0x10);
                        pbVar34[0] = 0;
                        pbVar34[1] = 0;
                        pbVar34[2] = 0;
                        pbVar34[3] = 0;
                        pbVar34[4] = 0;
                        pbVar34[5] = 0;
                        pbVar34[6] = 0;
                        pbVar34[7] = 0;
                        pbVar34[8] = 0;
                        pbVar34[9] = 0;
                        pbVar34[10] = 0;
                        pbVar34[0xb] = 0;
                        pbVar34[0xc] = 0;
                        pbVar34[0xd] = 0;
                        pbVar34[0xe] = 0;
                        pbVar34[0xf] = 0;
                        pbVar34[0x10] = 0;
                        pbVar34[0x11] = 0;
                        pbVar34[0x12] = 0;
                        pbVar34[0x13] = 0;
                        pbVar34[0x14] = 0;
                        pbVar34[0x15] = 0;
                        pbVar34[0x16] = 0;
                        pbVar34[0x17] = 0;
                        if (((byte)local_c8 & 1) != 0) {
                          operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                        }
                        if (((ulong)pvVar68 & 1) != 0) {
                          operator_delete(pvVar12);
                        }
                        AVar65 = SUB81(local_228,0);
                        uStack_2fe = local_58._8_6_;
                        uStack_306 = local_58._0_6_;
                        uStack_300 = local_58._6_2_;
                        pbVar50 = pbVar50 + 0x18;
                        pvVar68 = local_228;
                        local_308 = AVar65;
                        AStack_307 = AVar69;
                        local_2f8 = pvVar24;
                      } while (pbVar50 != local_1d0);
                    }
                    auVar78 = local_1c8;
                    local_1c8._6_2_ = uStack_300;
                    local_1c8._0_6_ = uStack_306;
                    local_1c8._14_2_ = auVar78._14_2_;
                    local_1c8._8_8_ =
                         (undefined8)
                         (CONCAT28(local_1c8._14_2_,CONCAT62(uStack_2fe,uStack_300)) >> 0x10);
                    local_308 = (ATCAircraftFlightPlan)0x0;
                    AStack_307 = (ATCAircraftFlightPlan)0x0;
                    uStack_306 = 0;
                    uStack_300 = 0;
                    uStack_2fe = 0;
                    local_2f8 = (void *)0x0;
                    if (((byte)*local_2c0 & 1) != 0) {
                      operator_delete(*(void **)(local_1d8 + 0x60));
                    }
                    plVar66 = local_200;
                    local_1d8[0x50] = AVar65;
                    local_1d8[0x51] = AVar69;
                    uVar32 = local_1c8._0_8_;
                    *(undefined8 *)(local_328 + 6) = local_1c8._6_8_;
                    *(undefined8 *)local_328 = uVar32;
                    *(void **)(local_1d8 + 0x60) = pvVar24;
                    if ((*local_1f8 & 1) == 0) {
                      uVar53 = (ulong)(*local_1f8 >> 1);
                    }
                    else {
                      uVar53 = *(ulong *)(local_1f8 + 8);
                    }
                    iVar20 = 0;
                    bVar18 = true;
                    if (uVar53 != 0) goto LAB_0027d44a;
                    iVar20 = 7;
                    if (((ulong)(((long)pbStack_1f0 - (long)local_1f8 >> 3) * -0x5555555555555555) <
                         2) || (cVar17 = ATCUtilsIsNearbyAirway
                                                   ((string *)(local_1f8 + 0x18),
                                                    (GeoPoint2D *)local_248), pbVar50 = pbStack_1f0,
                               cVar17 == '\0')) goto LAB_0027d447;
                    pbVar34 = local_1f8 + 0x18;
                    pbVar49 = local_1f8;
                    pbVar51 = local_1f8;
                    if (pbVar34 == pbStack_1f0) {
LAB_0027d57d:
                      do {
                        pbVar50 = pbVar34 + -0x18;
                        if ((pbVar34[-0x18] & 1) != 0) {
                          operator_delete(*(void **)(pbVar34 + -8));
                        }
                        pbVar34 = pbVar50;
                      } while (pbVar50 != pbVar49);
                    }
                    else {
                      do {
                        if ((*pbVar51 & 1) != 0) {
                          operator_delete(*(void **)(pbVar51 + 0x10));
                        }
                        pbVar49 = pbVar51 + 0x18;
                        *(undefined8 *)(pbVar51 + 0x10) = *(undefined8 *)(pbVar51 + 0x28);
                        *(undefined8 *)pbVar51 = *(undefined8 *)(pbVar51 + 0x18);
                        *(undefined8 *)(pbVar51 + 8) = *(undefined8 *)(pbVar51 + 0x20);
                        pbVar51[0x18] = 0;
                        pbVar51[0x19] = 0;
                        pbVar34 = pbVar51 + 0x30;
                        pbVar51 = pbVar49;
                      } while (pbVar34 != pbVar50);
                      pbVar34 = pbStack_1f0;
                      if (pbVar49 != pbStack_1f0) goto LAB_0027d57d;
                    }
                    iVar20 = 0;
                    plVar6 = (long *)CONCAT26(uStack_18a,local_190);
                    pbStack_1f0 = pbVar49;
                  }
                  else {
                    ATCNamedTransition::GetLastKnownPoint
                              ((ATCNamedTransition *)CONCAT26(uStack_192,local_198),
                               (GeoPoint2D *)local_248);
                    lVar67 = local_210;
                    local_c8 = (ATCAircraft)0x0;
                    uStack_c7 = 0;
                    cStack_c3 = '\0';
                    cStack_c2 = '\0';
                    cStack_c1 = '\0';
                    AStack_c0 = (ATCAircraft)0x0;
                    uStack_bf = 0;
                    local_b8 = (ATCAircraft)0x0;
                    uStack_b7 = 0;
                    uStack_b6 = 0;
                    local_268 = (vec_nav_struct *)0x0;
                    local_260 = (__tree_node)0x0;
                    if (local_229 == '\0') {
LAB_0027c3d7:
                      ATCControllerCab::GetBestRunway
                                (local_2b8,local_278,true,(runway_spec_t *)&local_268,
                                 (apt_flow_runway_rule **)&local_280,false,false);
                      if (local_268 != (vec_nav_struct *)0x0) goto LAB_0027c415;
LAB_0027c4c7:
                      if (((byte)local_c8 & 1) != 0) {
                        operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                      }
                      goto LAB_0027c703;
                    }
                    lVar46 = start_loc_spec::get_runway_start(local_3a0);
                    local_268 = *(vec_nav_struct **)(lVar46 + 8);
                    local_260 = *(__tree_node *)(lVar46 + 0x10);
                    p_Var48 = (__tree_node *)&local_318;
                    p_Var60 = local_318;
                    if (local_318 == (__tree_node *)0x0) {
LAB_0027c3cc:
                      local_268 = (vec_nav_struct *)0x0;
                      goto LAB_0027c3d7;
                    }
                    do {
                      while ((local_268 <= *(__tree_node **)(p_Var60 + 0x20) &&
                             ((*(__tree_node **)(p_Var60 + 0x20) != (__tree_node *)local_268 ||
                              ((byte)local_260 <= (byte)p_Var60[0x28]))))) {
                        p_Var59 = *(__tree_node **)p_Var60;
                        p_Var48 = p_Var60;
                        p_Var60 = p_Var59;
                        if (p_Var59 == (__tree_node *)0x0) goto LAB_0027b754;
                      }
                      p_Var59 = p_Var60 + 8;
                      p_Var60 = *(__tree_node **)p_Var59;
                    } while (*(__tree_node **)p_Var59 != (__tree_node *)0x0);
LAB_0027b754:
                    if (((p_Var48 == (__tree_node *)&local_318) ||
                        (local_268 < *(__tree_node **)(p_Var48 + 0x20))) ||
                       ((local_268 <= *(__tree_node **)(p_Var48 + 0x20) &&
                        ((byte)local_260 < (byte)p_Var48[0x28])))) goto LAB_0027c3cc;
                    plVar66 = *(long **)(CONCAT26(uStack_192,local_198) + 0x10);
                    runway_spec_t::nameForAIRNAV();
                    cVar17 = (**(code **)(*plVar66 + 0x48))(plVar66,local_58);
                    lVar67 = local_210;
                    if (((byte)local_58[0] & 1) != 0) {
                      operator_delete(local_48);
                    }
                    if (cVar17 == '\0') goto LAB_0027c3cc;
                    if (local_268 == (vec_nav_struct *)0x0) goto LAB_0027c3d7;
LAB_0027c415:
                    runway_spec_t::nameForAIRNAV();
                    if (((byte)local_c8 & 1) != 0) {
                      operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                    }
                    local_b8 = SUB81(local_48,0);
                    uStack_b7 = (undefined1)((ulong)local_48 >> 8);
                    uStack_b6 = (undefined6)((ulong)local_48 >> 0x10);
                    local_c8 = local_58[0];
                    uStack_c7 = local_58._1_4_;
                    cStack_c3 = local_58[5];
                    cStack_c2 = local_58[6];
                    cStack_c1 = local_58[7];
                    AStack_c0 = local_58[8];
                    uStack_bf = local_58._9_7_;
                    plVar66 = *(long **)(CONCAT26(uStack_192,local_198) + 0x10);
                    cVar17 = (**(code **)(*plVar66 + 0x48))(plVar66,&local_c8);
                    if (cVar17 == '\0') {
                      local_268 = (vec_nav_struct *)0x0;
                      local_260 = (__tree_node)0x0;
                      p_Var48 = local_320;
                      while (p_Var60 = p_Var48, p_Var60 != (__tree_node *)&local_318) {
                        runway_spec_t::nameForAIRNAV();
                        if (((byte)local_c8 & 1) != 0) {
                          operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                        }
                        local_b8 = SUB81(local_48,0);
                        uStack_b7 = (undefined1)((ulong)local_48 >> 8);
                        uStack_b6 = (undefined6)((ulong)local_48 >> 0x10);
                        local_c8 = local_58[0];
                        uStack_c7 = local_58._1_4_;
                        cStack_c3 = local_58[5];
                        cStack_c2 = local_58[6];
                        cStack_c1 = local_58[7];
                        AStack_c0 = local_58[8];
                        uStack_bf = local_58._9_7_;
                        plVar66 = *(long **)(CONCAT26(uStack_192,local_198) + 0x10);
                        cVar17 = (**(code **)(*plVar66 + 0x48))(plVar66,&local_c8);
                        if (cVar17 != '\0') {
                          local_268 = *(vec_nav_struct **)(p_Var60 + 0x20);
                          local_260 = p_Var60[0x28];
                          break;
                        }
                        p_Var59 = *(__tree_node **)(p_Var60 + 8);
                        if (*(__tree_node **)(p_Var60 + 8) == (__tree_node *)0x0) {
                          p_Var48 = *(__tree_node **)(p_Var60 + 0x10);
                          if (*(__tree_node **)*(__tree_node **)(p_Var60 + 0x10) != p_Var60) {
                            do {
                              p_Var60 = *(__tree_node **)(p_Var60 + 0x10);
                              p_Var48 = *(__tree_node **)(p_Var60 + 0x10);
                            } while (*(__tree_node **)*(__tree_node **)(p_Var60 + 0x10) != p_Var60);
                          }
                        }
                        else {
                          do {
                            p_Var48 = p_Var59;
                            p_Var59 = *(__tree_node **)p_Var48;
                          } while (p_Var59 != (__tree_node *)0x0);
                        }
                      }
                    }
                    if (local_268 != (vec_nav_struct *)0x0) {
                      ATCControllerCab::ClearAircraftRunwayAssignment(local_2b8,local_278);
                      ATCControllerCab::AssignRunwayForAircraft
                                (local_2b8,local_278,(runway_spec_t *)&local_268);
                      goto LAB_0027c4c7;
                    }
                    local_1c8._0_6_ = 0x2044495308;
                    if ((local_1f8[lVar67 * 8] & 1) == 0) {
                      pbVar50 = local_1f8 + lVar67 * 8 + 1;
                    }
                    else {
                      pbVar50 = *(byte **)(local_1f8 + lVar67 * 8 + 0x10);
                    }
                    pauVar33 = (undefined1 (*) [16])std::string::append(local_1c8,(ulong)pbVar50);
                    local_48 = *(undefined1 **)pauVar33[1];
                    local_58 = *pauVar33;
                    *(undefined8 *)*pauVar33 = 0;
                    *(undefined8 *)(*pauVar33 + 8) = 0;
                    *(undefined8 *)pauVar33[1] = 0;
                    pcVar56 = operator_new(0x40);
                    uVar32 = s_is_not_usable_with_any_active_de_027cec43._40_8_;
                    *(undefined8 *)(pcVar56 + 0x20) =
                         s_is_not_usable_with_any_active_de_027cec43._32_8_;
                    *(undefined8 *)(pcVar56 + 0x28) = uVar32;
                    uVar32 = s_is_not_usable_with_any_active_de_027cec43._24_8_;
                    *(undefined8 *)(pcVar56 + 0x10) =
                         s_is_not_usable_with_any_active_de_027cec43._16_8_;
                    *(undefined8 *)(pcVar56 + 0x18) = uVar32;
                    uVar32 = s_is_not_usable_with_any_active_de_027cec43._8_8_;
                    *(undefined8 *)pcVar56 = s_is_not_usable_with_any_active_de_027cec43._0_8_;
                    *(undefined8 *)(pcVar56 + 8) = uVar32;
                    pcVar56[0x30] = '\0';
                    pbVar34 = (byte *)std::string::append(local_58,(ulong)pcVar56);
                    pbVar50 = local_220;
                    bVar43 = *pbVar34;
                    bVar2 = pbVar34[1];
                    uStack_1a0 = (undefined6)((ulong)*(undefined8 *)(pbVar34 + 8) >> 0x10);
                    local_1a8._0_6_ = (undefined6)*(undefined8 *)(pbVar34 + 2);
                    local_1a8._6_2_ = (undefined2)((ulong)*(undefined8 *)(pbVar34 + 2) >> 0x30);
                    uVar32 = *(undefined8 *)(pbVar34 + 0x10);
                    pbVar34[0] = 0;
                    pbVar34[1] = 0;
                    pbVar34[2] = 0;
                    pbVar34[3] = 0;
                    pbVar34[4] = 0;
                    pbVar34[5] = 0;
                    pbVar34[6] = 0;
                    pbVar34[7] = 0;
                    pbVar34[8] = 0;
                    pbVar34[9] = 0;
                    pbVar34[10] = 0;
                    pbVar34[0xb] = 0;
                    pbVar34[0xc] = 0;
                    pbVar34[0xd] = 0;
                    pbVar34[0xe] = 0;
                    pbVar34[0xf] = 0;
                    pbVar34[0x10] = 0;
                    pbVar34[0x11] = 0;
                    pbVar34[0x12] = 0;
                    pbVar34[0x13] = 0;
                    pbVar34[0x14] = 0;
                    pbVar34[0x15] = 0;
                    pbVar34[0x16] = 0;
                    pbVar34[0x17] = 0;
                    if ((*local_220 & 1) != 0) {
                      operator_delete(*(void **)(local_220 + 0x10));
                    }
                    *pbVar50 = bVar43;
                    pbVar50[1] = bVar2;
                    *(ulong *)(local_258 + 6) = CONCAT62(uStack_1a0,local_1a8._6_2_);
                    *(ulong *)local_258 = CONCAT26(local_1a8._6_2_,(undefined6)local_1a8);
                    *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                    operator_delete(pcVar56);
                    if (((byte)local_58[0] & 1) == 0) {
                      if (((byte)local_1c8[0] & 1) != 0) goto LAB_0027cb0c;
LAB_0027ca9b:
                      bVar43 = *local_220;
                      plVar66 = local_200;
                    }
                    else {
                      operator_delete(local_48);
                      if (((byte)local_1c8[0] & 1) == 0) goto LAB_0027ca9b;
LAB_0027cb0c:
                      plVar66 = local_200;
                      operator_delete(local_1b8);
                      bVar43 = *local_220;
                    }
                    pbVar50 = local_390;
                    if ((bVar43 & 1) != 0) {
                      pbVar50 = *(byte **)(local_220 + 0x10);
                    }
                    _source_sim_log_write(3,"ATC","%s",pbVar50);
                    if (((byte)local_c8 & 1) != 0) {
                      operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                    }
                    iVar20 = 1;
LAB_0027d447:
                    bVar18 = false;
LAB_0027d44a:
                    plVar6 = (long *)CONCAT26(uStack_18a,local_190);
                  }
                  if (plVar6 != (long *)0x0) {
                    LOCK();
                    plVar1 = plVar6 + 1;
                    lVar67 = *plVar1;
                    *plVar1 = *plVar1 + -1;
                    UNLOCK();
                    if (lVar67 == 0) {
                      (**(code **)(*plVar6 + 0x10))(plVar6);
                      std::__shared_weak_count::__release_weak();
                    }
                  }
                  if (bVar18) goto LAB_0027d47e;
                  if (((byte)local_170 & 1) == 0) goto LAB_0027d4ad;
LAB_0027d48a:
                  operator_delete(local_160);
                }
                if ((void *)local_158._0_8_ != (void *)0x0) {
                  stack0xfffffffffffffeb0 = local_158._0_8_;
                  operator_delete((void *)local_158._0_8_);
                }
                uVar32 = local_e8._0_8_;
                if ((undefined8 *)local_e8._0_8_ != (undefined8 *)0x0) {
                  puVar38 = (undefined8 *)stack0xffffffffffffff20;
                  while (puVar38 != (undefined8 *)uVar32) {
                    puVar38 = puVar38 + -0x12;
                    (**(code **)*puVar38)(puVar38);
                  }
                  stack0xffffffffffffff20 = (Route *)uVar32;
                  operator_delete((void *)local_e8._0_8_);
                }
                uVar53 = local_2a0;
                if (iVar20 != 0) {
                  local_208 = 0;
                  if (iVar20 == 7) goto LAB_0027a610;
                  goto LAB_0027f1e8;
                }
              }
              lVar67 = local_210;
              if ((((long)pbStack_1f0 - (long)local_1f8 >> 3) * -0x5555555555555555 - 1U == uVar53)
                 && (local_290 != (vec_apt_struct *)0x0)) {
                if ((local_1f8[local_210 * 8] & 1) == 0) {
                  if (local_1f8[local_210 * 8] >> 1 == 3) goto LAB_0027a748;
                }
                else if (*(long *)(local_1f8 + local_210 * 8 + 8) == 3) {
LAB_0027a748:
                  iVar20 = std::string::compare
                                     ((ulong)(local_1f8 + local_210 * 8),0,
                                      (char *)0xffffffffffffffff,0x27cec3f);
                  if (iVar20 == 0) {
                    std::string::assign((char *)local_2a8);
                    goto LAB_0027a610;
                  }
                }
                _local_e8 = (undefined1  [16])0x0;
                local_d8 = (char *)0x0;
                local_2a0 = uVar53;
                pcVar56 = (char *)vec_apt_struct::get_id_for_navdata(local_290);
                sVar26 = _strlen(pcVar56);
                if (0xffffffffffffffef < sVar26) {
                    /* WARNING: Subroutine does not return */
                  std::string::__throw_length_error();
                }
                if (sVar26 < 0x17) {
                  local_c8 = (ATCAircraft)((char)SUB81(sVar26,0) * '\x02');
                  puVar31 = &uStack_c7;
                  if (sVar26 != 0) goto LAB_0027a7fe;
                }
                else {
                  uVar53 = sVar26 + 0x10 & 0xfffffffffffffff0;
                  puVar31 = operator_new(uVar53);
                  local_b8 = SUB81(puVar31,0);
                  uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                  uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                  local_c8 = (ATCAircraft)((byte)uVar53 | 1);
                  uStack_c7 = (uint)(uVar53 >> 8);
                  cStack_c3 = (char)(uVar53 >> 0x28);
                  cStack_c2 = (char)(uVar53 >> 0x30);
                  cStack_c1 = (char)(uVar53 >> 0x38);
                  uStack_bf = (undefined7)(sVar26 >> 8);
                  AStack_c0 = SUB81(sVar26,0);
LAB_0027a7fe:
                  _memcpy(puVar31,pcVar56,sVar26);
                }
                *(undefined1 *)((long)puVar31 + sVar26) = 0;
                AIRNAV5::Database::NavDataBase::
                getProcs<AIRNAV5::Navigation::StandardRoute<(AIRNAV5::Navigation::StandardRouteType)1>>
                          (local_330,(vector *)&local_c8,SUB81(local_e8,0));
                plVar66 = local_200;
                lVar67 = local_210;
                if (((byte)local_c8 & 1) != 0) {
                  operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                }
                local_128 = (undefined1  [16])0x0;
                local_118 = 0;
                local_110 = (undefined1  [16])0x0;
                local_100 = '\0';
                local_f8 = 0;
                local_f0 = 0;
                _local_158 = (undefined1  [16])0x0;
                local_148 = (char *)0x0;
                uStack_140._0_1_ = 0;
                uStack_140._1_7_ = 0;
                local_138._0_9_ = SUB169((undefined1  [16])0x0,7);
                std::string::string(&local_170,(string *)(local_1f8 + lVar67 * 8));
                if (((byte)local_170 & 1) == 0) {
                  uVar53 = (ulong)((byte)local_170 >> 1);
                  puVar71 = &uStack_16f;
                }
                else {
                  uVar53 = CONCAT26(uStack_162,local_168);
                  puVar71 = local_160;
                }
                local_98 = (undefined1  [16])0x0;
                local_88 = local_88 & 0xffffffffffffff00;
                local_80 = (undefined1  [16])0x0;
                local_70 = local_70 & 0xffffffffffffff00;
                local_68 = 0;
                local_60 = 0;
                local_c8 = (ATCAircraft)0x0;
                uStack_c7 = 0;
                cStack_c3 = '\0';
                cStack_c2 = '\0';
                cStack_c1 = '\0';
                AStack_c0 = (ATCAircraft)0x0;
                uStack_bf = 0;
                local_b8 = (ATCAircraft)0x0;
                uStack_b7 = 0;
                uStack_b6 = 0;
                uStack_b0 = 0;
                uStack_af = 0;
                local_a8 = (function *)0x0;
                uStack_a0 = 0;
                bVar18 = std::regex::__search<std::allocator<std::sub_match<char_const*>>>
                                   ((regex *)&ATCFlightRoute::reSTAR,puVar71,uVar53 + (long)puVar71,
                                    &local_c8,0x1040);
                std::
                match_results<std::__wrap_iter<char_const*>,std::allocator<std::sub_match<std::__wrap_iter<char_const*>>>>
                ::__assign<char_const*,std::allocator<std::sub_match<char_const*>>>
                          ((match_results<std::__wrap_iter<char_const*>,std::allocator<std::sub_match<std::__wrap_iter<char_const*>>>>
                            *)local_158,puVar71,uVar53 + (long)puVar71,&local_c8,0);
                pvVar24 = (void *)CONCAT17(cStack_c1,
                                           CONCAT16(cStack_c2,
                                                    CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))
                                                   ));
                if (pvVar24 != (void *)0x0) {
                  AStack_c0 = local_c8;
                  uStack_bf = (undefined7)((ulong)pvVar24 >> 8);
                  operator_delete(pvVar24);
                }
                iVar20 = 0;
                lVar67 = local_210;
                if (bVar18) {
                  if (local_100 == '\0') {
                    lVar67 = local_e8._0_8_;
                    lVar46 = (long)stack0xffffffffffffff20;
                    puVar38 = (undefined8 *)(local_158._0_8_ + 0x30);
                    if ((ulong)((stack0xfffffffffffffeb0 - local_158._0_8_ >> 3) *
                               -0x5555555555555555) < 3) {
                      puVar38 = &uStack_140;
                    }
                    local_388 = *puVar38;
                    uStack_380 = puVar38[1];
                    local_378 = *(undefined1 *)(puVar38 + 2);
                    std::string::string(&local_370,&local_170);
                    lVar63 = lVar67;
                    for (; lVar67 != lVar46; lVar67 = lVar67 + 0x90) {
                      AIRNAV5::Navigation::Procedure::name();
                      bVar19 = std::operator==((basic_string *)&local_c8,(sub_match *)&local_388);
                      bVar18 = true;
                      if (!bVar19) {
                        AIRNAV5::Navigation::Procedure::name();
                        puVar55 = local_48;
                        uVar53 = (ulong)((byte)local_58[0] >> 1);
                        if (((byte)local_58[0] & 1) != 0) {
                          uVar53 = local_58._8_8_;
                        }
                        if (((byte)local_370 & 1) == 0) {
                          if (uVar53 != (byte)local_370 >> 1) goto LAB_0027b935;
LAB_0027b950:
                          puVar61 = local_36f;
                          if (((byte)local_370 & 1) != 0) {
                            puVar61 = local_360;
                          }
                          if (((byte)local_58[0] & 1) == 0) {
                            if (uVar53 == 0) {
                              bVar18 = true;
                              goto LAB_0027b9cd;
                            }
                            lVar63 = 0;
                            do {
                              bVar18 = local_58[lVar63 + 1] == puVar61[lVar63];
                              if (!bVar18) break;
                              bVar19 = (ulong)((byte)local_58[0] >> 1) - 1 != lVar63;
                              lVar63 = lVar63 + 1;
                            } while (bVar19);
                            goto LAB_0027b937;
                          }
                          if (uVar53 == 0) {
                            bVar18 = true;
                          }
                          else {
                            iVar20 = _memcmp(local_48,puVar61,uVar53);
                            bVar18 = iVar20 == 0;
                          }
                        }
                        else {
                          if (uVar53 == local_368) goto LAB_0027b950;
LAB_0027b935:
                          bVar18 = false;
LAB_0027b937:
                          if (((byte)local_58[0] & 1) == 0) goto LAB_0027b9cd;
                        }
                        operator_delete(puVar55);
                      }
LAB_0027b9cd:
                      if (((byte)local_c8 & 1) != 0) {
                        operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                      }
                      lVar63 = lVar67;
                      if (bVar18) break;
                      lVar63 = lVar46;
                    }
                    lVar67 = local_210;
                    iVar20 = 0;
                    if (((byte)local_370 & 1) != 0) {
                      operator_delete(local_360);
                    }
                    psVar47 = local_2a8;
                    plVar66 = local_200;
                    if ((Route *)lVar63 != stack0xffffffffffffff20) {
                      if (((byte)*local_2a8 & 1) == 0) {
                        *(undefined2 *)local_2a8 = 0;
                      }
                      else {
                        **(undefined1 **)(local_1d8 + 0x98) = 0;
                        *(undefined8 *)(local_1d8 + 0x90) = 0;
                      }
                      uVar53 = (stack0xfffffffffffffeb0 - local_158._0_8_ >> 3) *
                               -0x5555555555555555;
                      pcVar56 = (char *)(local_158._0_8_ + 0x28);
                      if (uVar53 < 2) {
                        pcVar56 = local_138 + 8;
                      }
                      if (*pcVar56 != '\0') {
                        puVar39 = (undefined8 *)(local_158._0_8_ + 0x20);
                        puVar38 = (undefined8 *)(local_158._0_8_ + 0x18);
                        if (uVar53 < 2) {
                          puVar39 = (undefined8 *)local_138;
                          puVar38 = &uStack_140;
                        }
                        puVar55 = (undefined1 *)*puVar38;
                        puVar61 = (undefined1 *)*puVar39;
                        uVar53 = (long)puVar61 - (long)puVar55;
                        if (0xffffffffffffffef < uVar53) {
                    /* WARNING: Subroutine does not return */
                          std::string::__throw_length_error();
                        }
                        if (uVar53 < 0x17) {
                          local_c8 = (ATCAircraft)((char)SUB81(uVar53,0) * '\x02');
                          puVar31 = &uStack_c7;
                        }
                        else {
                          uVar25 = uVar53 + 0x10 & 0xfffffffffffffff0;
                          puVar31 = operator_new(uVar25);
                          local_b8 = SUB81(puVar31,0);
                          uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                          uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                          local_c8 = (ATCAircraft)((byte)uVar25 | 1);
                          uStack_c7 = (uint)(uVar25 >> 8);
                          cStack_c3 = (char)(uVar25 >> 0x28);
                          cStack_c2 = (char)(uVar25 >> 0x30);
                          cStack_c1 = (char)(uVar25 >> 0x38);
                          uStack_bf = (undefined7)(uVar53 >> 8);
                          AStack_c0 = SUB81(uVar53,0);
                        }
                        if (puVar55 != puVar61) {
                          if ((0x1f < uVar53) &&
                             ((puVar55 + uVar53 <= puVar31 ||
                              ((undefined1 *)((long)puVar31 + uVar53) <= puVar55)))) {
                            uVar64 = uVar53 & 0xffffffffffffffe0;
                            uVar62 = (uVar64 - 0x20 >> 5) + 1;
                            uVar25 = (ulong)((uint)uVar62 & 3);
                            if (uVar64 - 0x20 < 0x60) {
                              lVar46 = 0;
                            }
                            else {
                              lVar67 = -(uVar62 & 0xfffffffffffffffc);
                              lVar46 = 0;
                              do {
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x10);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x10) + 8);
                                *(undefined8 *)((long)puVar31 + lVar46) =
                                     *(undefined8 *)(puVar55 + lVar46);
                                ((undefined8 *)((long)puVar31 + lVar46))[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x10);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x20) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x30);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x30) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x20);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x20);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x30);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x40) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x50);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x50) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x40);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x40);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x50);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x60) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x70);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x70) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x60);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x60);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x70);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                lVar46 = lVar46 + 0x80;
                                lVar67 = lVar67 + 4;
                              } while (lVar67 != 0);
                            }
                            if (uVar25 != 0) {
                              lVar67 = 0;
                              do {
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar67 + lVar46) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar67 + lVar46 + 0x10);
                                uVar5 = *(undefined8 *)
                                         ((long)(puVar55 + lVar67 + lVar46 + 0x10) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar67 + lVar46);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar67 + lVar46);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar67 + lVar46 + 0x10);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                lVar67 = lVar67 + 0x20;
                              } while (uVar25 << 5 != lVar67);
                            }
                            puVar31 = (uint *)((long)puVar31 + uVar64);
                            if (uVar53 == uVar64) goto LAB_0027d6b3;
                            puVar55 = puVar55 + uVar64;
                          }
                          uVar21 = (int)puVar61 - (int)puVar55;
                          uVar25 = ~(ulong)puVar55;
                          uVar53 = (ulong)uVar21 & 7;
                          if ((uVar21 & 7) != 0) {
                            do {
                              *(undefined1 *)puVar31 = *puVar55;
                              puVar55 = puVar55 + 1;
                              puVar31 = (uint *)((long)puVar31 + 1);
                              uVar53 = uVar53 - 1;
                            } while (uVar53 != 0);
                          }
                          if ((undefined1 *)0x6 < puVar61 + uVar25) {
                            do {
                              *(undefined1 *)puVar31 = *puVar55;
                              *(undefined1 *)((long)puVar31 + 1) = puVar55[1];
                              *(undefined1 *)((long)puVar31 + 2) = puVar55[2];
                              *(undefined1 *)((long)puVar31 + 3) = puVar55[3];
                              *(undefined1 *)(puVar31 + 1) = puVar55[4];
                              *(undefined1 *)((long)puVar31 + 5) = puVar55[5];
                              *(undefined1 *)((long)puVar31 + 6) = puVar55[6];
                              *(undefined1 *)((long)puVar31 + 7) = puVar55[7];
                              puVar31 = puVar31 + 2;
                              puVar55 = puVar55 + 8;
                            } while (puVar55 != puVar61);
                          }
                        }
LAB_0027d6b3:
                        *(undefined1 *)puVar31 = 0;
                        pAVar42 = (ATCAircraftFlightPlan *)std::string::append((char *)&local_c8);
                        AVar69 = *pAVar42;
                        AVar65 = pAVar42[1];
                        local_58._8_8_ =
                             (undefined8)
                             (CONCAT28(local_58._14_2_,*(undefined8 *)(pAVar42 + 8)) >> 0x10);
                        local_58._0_8_ = *(undefined8 *)(pAVar42 + 2);
                        uVar32 = *(undefined8 *)(pAVar42 + 0x10);
                        *(undefined1 (*) [16])pAVar42 = (undefined1  [16])0x0;
                        *(undefined8 *)(pAVar42 + 0x10) = 0;
                        if (((byte)*psVar47 & 1) != 0) {
                          operator_delete(*(void **)(local_1d8 + 0x98));
                        }
                        local_1d8[0x88] = AVar69;
                        local_1d8[0x89] = AVar65;
                        uVar4 = local_58._0_8_;
                        *(undefined8 *)(local_398 + 6) = local_58._6_8_;
                        *(undefined8 *)local_398 = uVar4;
                        *(undefined8 *)(local_1d8 + 0x98) = uVar32;
                        if (((byte)local_c8 & 1) != 0) {
                          operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                        }
                        uVar53 = (stack0xfffffffffffffeb0 - local_158._0_8_ >> 3) *
                                 -0x5555555555555555;
                        lVar67 = local_210;
                      }
                      pcVar56 = (char *)(local_158._0_8_ + 0x40);
                      if (uVar53 < 3) {
                        pcVar56 = local_138 + 8;
                      }
                      if (*pcVar56 == '\0') {
                        local_c8 = (ATCAircraft)0x0;
                        uStack_c7 = 0;
                        cStack_c3 = '\0';
                        cStack_c2 = '\0';
                        cStack_c1 = '\0';
                        AStack_c0 = (ATCAircraft)0x0;
                        uStack_bf = 0;
                        local_b8 = (ATCAircraft)0x0;
                        uStack_b7 = 0;
                        uStack_b6 = 0;
                        puVar31 = (uint *)0x0;
                      }
                      else {
                        puVar39 = (undefined8 *)(local_158._0_8_ + 0x38);
                        puVar38 = (undefined8 *)(local_158._0_8_ + 0x30);
                        if (uVar53 < 3) {
                          puVar39 = (undefined8 *)local_138;
                          puVar38 = &uStack_140;
                        }
                        puVar55 = (undefined1 *)*puVar38;
                        puVar61 = (undefined1 *)*puVar39;
                        uVar53 = (long)puVar61 - (long)puVar55;
                        if (0xffffffffffffffef < uVar53) {
                    /* WARNING: Subroutine does not return */
                          std::string::__throw_length_error();
                        }
                        if (uVar53 < 0x17) {
                          local_c8 = (ATCAircraft)((char)SUB81(uVar53,0) * '\x02');
                          puVar31 = &uStack_c7;
                        }
                        else {
                          uVar25 = uVar53 + 0x10 & 0xfffffffffffffff0;
                          puVar31 = operator_new(uVar25);
                          local_b8 = SUB81(puVar31,0);
                          uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                          uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                          local_c8 = (ATCAircraft)((byte)uVar25 | 1);
                          uStack_c7 = (uint)(uVar25 >> 8);
                          cStack_c3 = (char)(uVar25 >> 0x28);
                          cStack_c2 = (char)(uVar25 >> 0x30);
                          cStack_c1 = (char)(uVar25 >> 0x38);
                          uStack_bf = (undefined7)(uVar53 >> 8);
                          AStack_c0 = SUB81(uVar53,0);
                        }
                        if (puVar55 != puVar61) {
                          if ((0x1f < uVar53) &&
                             ((puVar55 + uVar53 <= puVar31 ||
                              ((undefined1 *)((long)puVar31 + uVar53) <= puVar55)))) {
                            uVar64 = uVar53 & 0xffffffffffffffe0;
                            uVar62 = (uVar64 - 0x20 >> 5) + 1;
                            uVar25 = (ulong)((uint)uVar62 & 3);
                            if (uVar64 - 0x20 < 0x60) {
                              lVar46 = 0;
                            }
                            else {
                              lVar67 = -(uVar62 & 0xfffffffffffffffc);
                              lVar46 = 0;
                              do {
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x10);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x10) + 8);
                                *(undefined8 *)((long)puVar31 + lVar46) =
                                     *(undefined8 *)(puVar55 + lVar46);
                                ((undefined8 *)((long)puVar31 + lVar46))[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x10);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x20) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x30);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x30) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x20);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x20);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x30);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x40) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x50);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x50) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x40);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x40);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x50);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x60) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + 0x70);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar46 + 0x70) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x60);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar46 + 0x60);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + 0x70);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                lVar46 = lVar46 + 0x80;
                                lVar67 = lVar67 + 4;
                              } while (lVar67 != 0);
                            }
                            if (uVar25 != 0) {
                              lVar67 = 0;
                              do {
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar67 + lVar46) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar67 + lVar46 + 0x10);
                                uVar5 = *(undefined8 *)
                                         ((long)(puVar55 + lVar67 + lVar46 + 0x10) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar67 + lVar46);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar67 + lVar46);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar67 + lVar46 + 0x10);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                lVar67 = lVar67 + 0x20;
                              } while (uVar25 << 5 != lVar67);
                            }
                            puVar31 = (uint *)((long)puVar31 + uVar64);
                            if (uVar53 == uVar64) goto LAB_0027d9a3;
                            puVar55 = puVar55 + uVar64;
                          }
                          uVar21 = (int)puVar61 - (int)puVar55;
                          uVar25 = ~(ulong)puVar55;
                          uVar53 = (ulong)uVar21 & 7;
                          if ((uVar21 & 7) != 0) {
                            do {
                              *(undefined1 *)puVar31 = *puVar55;
                              puVar55 = puVar55 + 1;
                              puVar31 = (uint *)((long)puVar31 + 1);
                              uVar53 = uVar53 - 1;
                            } while (uVar53 != 0);
                          }
                          if ((undefined1 *)0x6 < puVar61 + uVar25) {
                            do {
                              *(undefined1 *)puVar31 = *puVar55;
                              *(undefined1 *)((long)puVar31 + 1) = puVar55[1];
                              *(undefined1 *)((long)puVar31 + 2) = puVar55[2];
                              *(undefined1 *)((long)puVar31 + 3) = puVar55[3];
                              *(undefined1 *)(puVar31 + 1) = puVar55[4];
                              *(undefined1 *)((long)puVar31 + 5) = puVar55[5];
                              *(undefined1 *)((long)puVar31 + 6) = puVar55[6];
                              *(undefined1 *)((long)puVar31 + 7) = puVar55[7];
                              puVar31 = puVar31 + 2;
                              puVar55 = puVar55 + 8;
                            } while (puVar55 != puVar61);
                          }
                        }
LAB_0027d9a3:
                        *(undefined1 *)puVar31 = 0;
                        puVar31 = (uint *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
                        lVar67 = local_210;
                      }
                      puVar57 = &uStack_c7;
                      if (((byte)local_c8 & 1) != 0) {
                        puVar57 = puVar31;
                      }
                      std::string::append((char *)psVar47,(ulong)puVar57);
                      if (((byte)local_c8 & 1) != 0) {
                        operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                      }
                      uVar53 = (stack0xfffffffffffffeb0 - local_158._0_8_ >> 3) *
                               -0x5555555555555555;
                      pcVar56 = (char *)(local_158._0_8_ + 0x28);
                      if (uVar53 < 2) {
                        pcVar56 = local_138 + 8;
                      }
                      if (*pcVar56 == '\0') {
                        if ((local_1f8[lVar67 * 8] & 1) == 0) {
                          (local_1f8 + lVar67 * 8)[0] = 0;
                          (local_1f8 + lVar67 * 8)[1] = 0;
                        }
                        else {
                          **(undefined1 **)(local_1f8 + lVar67 * 8 + 0x10) = 0;
                          pbVar50 = local_1f8 + lVar67 * 8 + 8;
                          pbVar50[0] = 0;
                          pbVar50[1] = 0;
                          pbVar50[2] = 0;
                          pbVar50[3] = 0;
                          pbVar50[4] = 0;
                          pbVar50[5] = 0;
                          pbVar50[6] = 0;
                          pbVar50[7] = 0;
                        }
                      }
                      else {
                        puVar39 = (undefined8 *)(local_158._0_8_ + 0x20);
                        puVar38 = (undefined8 *)(local_158._0_8_ + 0x18);
                        if (uVar53 < 2) {
                          puVar39 = (undefined8 *)local_138;
                          puVar38 = &uStack_140;
                        }
                        puVar55 = (undefined1 *)*puVar38;
                        puVar61 = (undefined1 *)*puVar39;
                        uVar53 = (long)puVar61 - (long)puVar55;
                        if (0xffffffffffffffef < uVar53) {
                    /* WARNING: Subroutine does not return */
                          std::string::__throw_length_error();
                        }
                        if (uVar53 < 0x17) {
                          local_c8 = (ATCAircraft)((char)SUB81(uVar53,0) * '\x02');
                          puVar31 = &uStack_c7;
                        }
                        else {
                          uVar25 = uVar53 + 0x10 & 0xfffffffffffffff0;
                          puVar31 = operator_new(uVar25);
                          local_b8 = SUB81(puVar31,0);
                          uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                          uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                          local_c8 = (ATCAircraft)((byte)uVar25 | 1);
                          uStack_c7 = (uint)(uVar25 >> 8);
                          cStack_c3 = (char)(uVar25 >> 0x28);
                          cStack_c2 = (char)(uVar25 >> 0x30);
                          cStack_c1 = (char)(uVar25 >> 0x38);
                          uStack_bf = (undefined7)(uVar53 >> 8);
                          AStack_c0 = SUB81(uVar53,0);
                        }
                        pbVar50 = local_1f8;
                        lVar67 = local_210;
                        if (puVar55 != puVar61) {
                          if ((0x1f < uVar53) &&
                             ((puVar55 + uVar53 <= puVar31 ||
                              ((undefined1 *)((long)puVar31 + uVar53) <= puVar55)))) {
                            uVar64 = uVar53 & 0xffffffffffffffe0;
                            uVar62 = (uVar64 - 0x20 >> 5) + 1;
                            uVar25 = (ulong)((uint)uVar62 & 3);
                            if (uVar64 - 0x20 < 0x60) {
                              lVar63 = 0;
                            }
                            else {
                              lVar46 = -(uVar62 & 0xfffffffffffffffc);
                              lVar63 = 0;
                              do {
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar63) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar63 + 0x10);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar63 + 0x10) + 8);
                                *(undefined8 *)((long)puVar31 + lVar63) =
                                     *(undefined8 *)(puVar55 + lVar63);
                                ((undefined8 *)((long)puVar31 + lVar63))[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar63 + 0x10);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar63 + 0x20) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar63 + 0x30);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar63 + 0x30) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar63 + 0x20);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar63 + 0x20);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar63 + 0x30);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar63 + 0x40) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar63 + 0x50);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar63 + 0x50) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar63 + 0x40);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar63 + 0x40);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar63 + 0x50);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar63 + 0x60) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar63 + 0x70);
                                uVar5 = *(undefined8 *)((long)(puVar55 + lVar63 + 0x70) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar63 + 0x60);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar63 + 0x60);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar63 + 0x70);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                lVar63 = lVar63 + 0x80;
                                lVar46 = lVar46 + 4;
                              } while (lVar46 != 0);
                            }
                            if (uVar25 != 0) {
                              lVar46 = 0;
                              do {
                                uVar32 = *(undefined8 *)((long)(puVar55 + lVar46 + lVar63) + 8);
                                uVar4 = *(undefined8 *)(puVar55 + lVar46 + lVar63 + 0x10);
                                uVar5 = *(undefined8 *)
                                         ((long)(puVar55 + lVar46 + lVar63 + 0x10) + 8);
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + lVar63);
                                *puVar38 = *(undefined8 *)(puVar55 + lVar46 + lVar63);
                                puVar38[1] = uVar32;
                                puVar38 = (undefined8 *)((long)puVar31 + lVar46 + lVar63 + 0x10);
                                *puVar38 = uVar4;
                                puVar38[1] = uVar5;
                                lVar46 = lVar46 + 0x20;
                              } while (uVar25 << 5 != lVar46);
                            }
                            puVar31 = (uint *)((long)puVar31 + uVar64);
                            if (uVar53 == uVar64) goto LAB_0027dc53;
                            puVar55 = puVar55 + uVar64;
                          }
                          uVar21 = (int)puVar61 - (int)puVar55;
                          uVar25 = ~(ulong)puVar55;
                          uVar53 = (ulong)uVar21 & 7;
                          if ((uVar21 & 7) != 0) {
                            do {
                              *(undefined1 *)puVar31 = *puVar55;
                              puVar55 = puVar55 + 1;
                              puVar31 = (uint *)((long)puVar31 + 1);
                              uVar53 = uVar53 - 1;
                            } while (uVar53 != 0);
                          }
                          if ((undefined1 *)0x6 < puVar61 + uVar25) {
                            do {
                              *(undefined1 *)puVar31 = *puVar55;
                              *(undefined1 *)((long)puVar31 + 1) = puVar55[1];
                              *(undefined1 *)((long)puVar31 + 2) = puVar55[2];
                              *(undefined1 *)((long)puVar31 + 3) = puVar55[3];
                              *(undefined1 *)(puVar31 + 1) = puVar55[4];
                              *(undefined1 *)((long)puVar31 + 5) = puVar55[5];
                              *(undefined1 *)((long)puVar31 + 6) = puVar55[6];
                              *(undefined1 *)((long)puVar31 + 7) = puVar55[7];
                              puVar31 = puVar31 + 2;
                              puVar55 = puVar55 + 8;
                            } while (puVar55 != puVar61);
                          }
                        }
LAB_0027dc53:
                        *(undefined1 *)puVar31 = 0;
                        if ((local_1f8[local_210 * 8] & 1) != 0) {
                          operator_delete(*(void **)(local_1f8 + local_210 * 8 + 0x10));
                        }
                        pbVar50 = pbVar50 + lVar67 * 8;
                        *(ulong *)(pbVar50 + 0x10) =
                             CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
                        *(ulong *)pbVar50 =
                             CONCAT17(cStack_c1,
                                      CONCAT16(cStack_c2,
                                               CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))));
                        *(ulong *)(pbVar50 + 8) = CONCAT71(uStack_bf,AStack_c0);
                      }
                      local_2e8 = (undefined1  [16])0x0;
                      local_1d0 = pbStack_1f0;
                      if (local_1f8 == pbStack_1f0) {
                        pvVar24 = (void *)0x0;
                        AVar65 = (ATCAircraftFlightPlan)0x0;
                        AVar69 = (ATCAircraftFlightPlan)0x0;
                      }
                      else {
                        local_228 = (void *)0x0;
                        pbVar50 = local_1f8;
                        pvVar24 = local_228;
                        AVar70 = (ATCAircraftFlightPlan)0x0;
                        do {
                          local_228 = pvVar24;
                          local_2d8 = local_228;
                          std::operator+((string *)&local_c8,local_2e8);
                          pbVar34 = pbVar50 + 1;
                          if ((*pbVar50 & 1) != 0) {
                            pbVar34 = *(byte **)(pbVar50 + 0x10);
                          }
                          pAVar42 = (ATCAircraftFlightPlan *)
                                    std::string::append((char *)&local_c8,(ulong)pbVar34);
                          AVar69 = *pAVar42;
                          AVar65 = pAVar42[1];
                          uVar8 = *(undefined2 *)pAVar42;
                          local_58._8_8_ =
                               (undefined8)
                               (CONCAT28(local_58._14_2_,*(undefined8 *)(pAVar42 + 8)) >> 0x10);
                          local_58._0_8_ = *(undefined8 *)(pAVar42 + 2);
                          pvVar24 = *(void **)(pAVar42 + 0x10);
                          *(undefined1 (*) [16])pAVar42 = (undefined1  [16])0x0;
                          *(undefined8 *)(pAVar42 + 0x10) = 0;
                          if (((byte)local_c8 & 1) != 0) {
                            operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8))
                                           );
                          }
                          if (((byte)AVar70 & 1) != 0) {
                            operator_delete(local_228);
                          }
                          local_2e8._10_6_ = local_58._8_6_;
                          local_2e8._2_8_ = local_58._0_8_;
                          local_2e8._0_2_ = uVar8;
                          pbVar50 = pbVar50 + 0x18;
                          AVar70 = AVar69;
                        } while (pbVar50 != local_1d0);
                      }
                      uVar32 = local_2e8._2_8_;
                      local_1c8._8_8_ =
                           (undefined8)(CONCAT28(local_1c8._14_2_,local_2e8._8_8_) >> 0x10);
                      local_1c8._0_8_ = uVar32;
                      local_2e8 = (undefined1  [16])0x0;
                      local_2d8 = (void *)0x0;
                      iVar20 = 0;
                      if (((byte)*local_2c0 & 1) != 0) {
                        operator_delete(*(void **)(local_1d8 + 0x60));
                      }
                      local_1d8[0x50] = AVar69;
                      local_1d8[0x51] = AVar65;
                      uVar32 = local_1c8._0_8_;
                      *(undefined8 *)(local_328 + 6) = local_1c8._6_8_;
                      *(undefined8 *)local_328 = uVar32;
                      *(void **)(local_1d8 + 0x60) = pvVar24;
                      if ((local_1f8[local_210 * 8] & 1) == 0) {
                        uVar53 = (ulong)(local_1f8[local_210 * 8] >> 1);
                      }
                      else {
                        uVar53 = *(ulong *)(local_1f8 + local_210 * 8 + 8);
                      }
                      plVar66 = local_200;
                      lVar67 = local_210;
                      if (uVar53 == 0) {
                        iVar20 = 5;
                      }
                    }
                  }
                  else {
                    stack0xfffffffffffffeb0 = local_158._0_8_;
                  }
                }
                if (((byte)local_170 & 1) != 0) {
                  operator_delete(local_160);
                }
                if ((void *)local_158._0_8_ != (void *)0x0) {
                  stack0xfffffffffffffeb0 = local_158._0_8_;
                  operator_delete((void *)local_158._0_8_);
                }
                uVar32 = local_e8._0_8_;
                if ((undefined8 *)local_e8._0_8_ != (undefined8 *)0x0) {
                  puVar38 = (undefined8 *)stack0xffffffffffffff20;
                  while (puVar38 != (undefined8 *)uVar32) {
                    puVar38 = puVar38 + -0x12;
                    (**(code **)*puVar38)(puVar38);
                  }
                  stack0xffffffffffffff20 = (Route *)uVar32;
                  operator_delete((void *)local_e8._0_8_);
                }
                uVar53 = local_2a0;
                if (iVar20 != 0) {
                  if (iVar20 != 5) goto LAB_0027f1df;
                  break;
                }
              }
              iVar20 = (int)local_208;
              if (iVar20 == 0) {
                cVar17 = ATCUtilsIsNearbyAirway
                                   ((string *)(local_1f8 + lVar67 * 8),(GeoPoint2D *)local_248);
                if (cVar17 == '\0') {
                  local_268 = (vec_nav_struct *)0x0;
                  local_1a8._0_6_ = 0;
                  local_1a8._6_2_ = 0;
                  local_280 = (vec_apt_struct *)0x0;
                  local_1c8._0_12_ = ZEXT812(0);
                  local_1d0 = (byte *)((ulong)local_1d0 & 0xffffffff00000000);
                  local_208 = 0;
                  goto LAB_0027acea;
                }
                local_218 = (awy_node_struct *)
                            ATCUtilsGetAwyStart(&local_6a0,(string *)(local_1f8 + lVar67 * 8),
                                                (GeoPoint2D *)local_248);
                pbVar50 = local_1f8;
                if (local_218 != (awy_node_struct *)0x0) {
                  lVar67 = *(long *)(local_218 + 8);
                  sVar26 = _strlen((char *)(lVar67 + 8));
                  if (0xffffffffffffffef < sVar26) {
                    /* WARNING: Subroutine does not return */
                    std::string::__throw_length_error();
                  }
                  if (sVar26 < 0x17) {
                    local_c8 = (ATCAircraft)((char)SUB81(sVar26,0) * '\x02');
                    puVar31 = &uStack_c7;
                    if (sVar26 != 0) goto LAB_0027b80a;
                  }
                  else {
                    uVar53 = sVar26 + 0x10 & 0xfffffffffffffff0;
                    puVar31 = operator_new(uVar53);
                    local_b8 = SUB81(puVar31,0);
                    uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                    uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                    local_c8 = (ATCAircraft)((byte)uVar53 | 1);
                    uStack_c7 = (uint)(uVar53 >> 8);
                    cStack_c3 = (char)(uVar53 >> 0x28);
                    cStack_c2 = (char)(uVar53 >> 0x30);
                    cStack_c1 = (char)(uVar53 >> 0x38);
                    uStack_bf = (undefined7)(sVar26 >> 8);
                    AStack_c0 = SUB81(sVar26,0);
LAB_0027b80a:
                    _memcpy(puVar31,(char *)(lVar67 + 8),sVar26);
                  }
                  *(undefined1 *)((long)puVar31 + sVar26) = 0;
                  std::vector<std::string,std::allocator<std::string>>::insert
                            ((vector<std::string,std::allocator<std::string>> *)&local_1f8,pbVar50,
                             &local_c8);
                  plVar66 = local_200;
                  if (((byte)local_c8 & 1) != 0) {
                    operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                  }
                  local_248._8_8_ = (double)(float)((ulong)**(undefined8 **)(local_218 + 8) >> 0x20)
                  ;
                  local_248._0_8_ = (double)(float)**(undefined8 **)(local_218 + 8);
                  local_208 = 0;
                  ATCRouteUtils::AppendIFRAirwayNode(local_250,local_218);
                  goto LAB_0027a610;
                }
                local_148 = operator_new(0x20);
                uVar32 = s_The_plan_starting_with_airway_027cec74._22_8_;
                stack0xfffffffffffffeb0 = _UNK_025203b8;
                local_158._0_8_ = _DAT_025203b0;
                *(ulong *)(local_148 + 0xe) =
                     CONCAT62(s_The_plan_starting_with_airway_027cec74._16_6_,
                              s_The_plan_starting_with_airway_027cec74._14_2_);
                *(undefined8 *)(local_148 + 0x16) = uVar32;
                uVar32 = CONCAT26(s_The_plan_starting_with_airway_027cec74._14_2_,
                                  s_The_plan_starting_with_airway_027cec74._8_6_);
                *(undefined8 *)local_148 = s_The_plan_starting_with_airway_027cec74._0_8_;
                *(undefined8 *)(local_148 + 8) = uVar32;
                local_148[0x1e] = '\0';
                if ((local_1f8[lVar67 * 8] & 1) == 0) {
                  pbVar50 = local_1f8 + lVar67 * 8 + 1;
                }
                else {
                  pbVar50 = *(byte **)(local_1f8 + lVar67 * 8 + 0x10);
                }
                pauVar33 = (undefined1 (*) [16])std::string::append(local_158,(ulong)pbVar50);
                uVar32 = *(undefined8 *)pauVar33[1];
                local_b8 = SUB81(uVar32,0);
                uStack_b7 = (undefined1)((ulong)uVar32 >> 8);
                uStack_b6 = (undefined6)((ulong)uVar32 >> 0x10);
                uVar32 = *(undefined8 *)*pauVar33;
                local_c8 = SUB81(uVar32,0);
                uStack_c7 = (uint)((ulong)uVar32 >> 8);
                cStack_c3 = (char)((ulong)uVar32 >> 0x28);
                cStack_c2 = (char)((ulong)uVar32 >> 0x30);
                cStack_c1 = (char)((ulong)uVar32 >> 0x38);
                AStack_c0 = SUB81(*(undefined8 *)(*pauVar33 + 8),0);
                uStack_bf = (undefined7)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 8);
                *pauVar33 = (undefined1  [16])0x0;
                *(undefined8 *)pauVar33[1] = 0;
                pcVar56 = operator_new(0x30);
                uVar32 = s_has_no_start_near_our_starting_l_027cec93._33_8_;
                *(ulong *)(pcVar56 + 0x19) =
                     CONCAT17(s_has_no_start_near_our_starting_l_027cec93[0x20],
                              s_has_no_start_near_our_starting_l_027cec93._25_7_);
                *(undefined8 *)(pcVar56 + 0x21) = uVar32;
                uVar32 = CONCAT71(s_has_no_start_near_our_starting_l_027cec93._25_7_,
                                  s_has_no_start_near_our_starting_l_027cec93[0x18]);
                *(undefined8 *)(pcVar56 + 0x10) = s_has_no_start_near_our_starting_l_027cec93._16_8_
                ;
                *(undefined8 *)(pcVar56 + 0x18) = uVar32;
                uVar32 = s_has_no_start_near_our_starting_l_027cec93._8_8_;
                *(undefined8 *)pcVar56 = s_has_no_start_near_our_starting_l_027cec93._0_8_;
                *(undefined8 *)(pcVar56 + 8) = uVar32;
                pcVar56[0x29] = '\0';
                pauVar33 = (undefined1 (*) [16])
                           std::string::append((char *)&local_c8,(ulong)pcVar56);
                pbVar50 = local_220;
                bVar43 = (*pauVar33)[0];
                bVar2 = (*pauVar33)[1];
                local_58._8_8_ =
                     (undefined8)(CONCAT28(local_58._14_2_,*(undefined8 *)(*pauVar33 + 8)) >> 0x10);
                local_58._0_8_ = *(undefined8 *)(*pauVar33 + 2);
                uVar32 = *(undefined8 *)pauVar33[1];
                *pauVar33 = (undefined1  [16])0x0;
                *(undefined8 *)pauVar33[1] = 0;
                if ((*local_220 & 1) != 0) {
                  operator_delete(*(void **)(local_220 + 0x10));
                }
                *pbVar50 = bVar43;
                pbVar50[1] = bVar2;
                uVar4 = local_58._0_8_;
                *(undefined8 *)(local_258 + 6) = local_58._6_8_;
                *(undefined8 *)local_258 = uVar4;
                *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                operator_delete(pcVar56);
                if (((byte)local_c8 & 1) == 0) {
                  if (((byte)local_158[0] & 1) != 0) goto LAB_0027ee0d;
LAB_0027edae:
                  AVar69 = local_1d8[0x50];
                  pAVar42 = local_270;
                  plVar66 = local_200;
                }
                else {
                  operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                  if (((byte)local_158[0] & 1) == 0) goto LAB_0027edae;
LAB_0027ee0d:
                  plVar66 = local_200;
                  pAVar42 = local_270;
                  operator_delete(local_148);
                  AVar69 = local_1d8[0x50];
                }
                if (((byte)AVar69 & 1) != 0) {
                  pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                }
                local_208 = 0;
                _source_sim_log_write(3,"ATC","Unable to parse route \'%s\' (airway not near start)",
                                  pAVar42);
                goto LAB_0027f1e8;
              }
              local_268 = (vec_nav_struct *)0x0;
              local_1a8._0_6_ = 0;
              local_1a8._6_2_ = 0;
              local_280 = (vec_apt_struct *)0x0;
              local_1c8._0_12_ = ZEXT812(0);
              if ((iVar20 < 1) ||
                 (((long)pbStack_1f0 - (long)local_1f8 >> 3) * -0x5555555555555555 - 1U <= uVar53))
              {
                local_1d0 = (byte *)((ulong)local_1d0 & 0xffffffff00000000);
              }
              else {
                if ((local_1f8[lVar67 * 8] & 1) == 0) {
                  pbVar50 = local_1f8 + lVar67 * 8 + 1;
                  uVar25 = (ulong)(local_1f8[lVar67 * 8] >> 1);
                }
                else {
                  uVar25 = *(ulong *)(local_1f8 + lVar67 * 8 + 8);
                  pbVar50 = *(byte **)(local_1f8 + lVar67 * 8 + 0x10);
                }
                to_uppercase(&local_c8,pbVar50,uVar25);
                bVar43 = (byte)local_c8 & 1;
                if (bVar43 == 0) {
                  if ((byte)local_c8 >> 1 != 3) goto LAB_0027accc;
LAB_0027b3eb:
                  iVar22 = std::string::compare
                                     ((ulong)&local_c8,0,(char *)0xffffffffffffffff,0x27cec3f);
                  uVar21 = (uint)CONCAT71((int7)(uVar53 >> 8),iVar22 == 0);
                  bVar43 = (byte)local_c8 & 1;
                }
                else {
                  if (CONCAT71(uStack_bf,AStack_c0) == 3) goto LAB_0027b3eb;
LAB_0027accc:
                  uVar21 = 0;
                }
                if (bVar43 != 0) {
                  operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                }
                local_1d0 = (byte *)CONCAT44(local_1d0._4_4_,uVar21);
                local_208 = (ulong)(iVar20 + (uVar21 & 0xff));
              }
LAB_0027acea:
              lVar67 = (long)(int)local_208;
              local_210 = lVar67 * 3;
              paVar29 = (awy_node_struct *)(lVar67 * 0x18);
              bVar43 = ATCUtilsIsNearbyAirway
                                 ((string *)(local_1f8 + (long)paVar29),(GeoPoint2D *)local_248);
              cVar17 = ATCUtilsParseVORRadial
                                 (&local_6a0,(string *)(local_1f8 + (long)paVar29),
                                  (GeoPoint2D *)local_248,local_1c8);
              if (cVar17 == '\0') {
                auVar78._8_8_ = 0;
                auVar78._0_8_ = local_1c8._8_8_;
                local_1c8 = auVar78 << 0x40;
              }
              if (((local_218 != (awy_node_struct *)0x0 & bVar43) == 1) &&
                 (cVar17 = has_incident_airway_by_name
                                     (local_218,(string *)(local_1f8 + (long)paVar29)),
                 auVar78 = local_58, cVar17 == '\0')) {
                local_58._1_8_ = 0x7772696120656854;
                local_58[0] = (sub_match)0x16;
                local_58._8_4_ = 0x20796177;
                local_58._13_3_ = auVar78._13_3_;
                local_58[0xc] = 0;
                if ((local_1f8[local_210 * 8] & 1) == 0) {
                  pbVar50 = local_1f8 + local_210 * 8 + 1;
                }
                else {
                  pbVar50 = *(byte **)(local_1f8 + local_210 * 8 + 0x10);
                }
                pauVar33 = (undefined1 (*) [16])std::string::append(local_58,(ulong)pbVar50);
                local_148 = *(char **)pauVar33[1];
                _local_158 = *pauVar33;
                *pauVar33 = (undefined1  [16])0x0;
                *(undefined8 *)pauVar33[1] = 0;
                pcVar56 = operator_new(0x30);
                uVar32 = s_is_not_attached_to_the_previous_w_027cecf0._34_8_;
                *(ulong *)(pcVar56 + 0x1a) =
                     CONCAT26(s_is_not_attached_to_the_previous_w_027cecf0._32_2_,
                              s_is_not_attached_to_the_previous_w_027cecf0._26_6_);
                *(undefined8 *)(pcVar56 + 0x22) = uVar32;
                uVar32 = CONCAT62(s_is_not_attached_to_the_previous_w_027cecf0._26_6_,
                                  s_is_not_attached_to_the_previous_w_027cecf0._24_2_);
                *(undefined8 *)(pcVar56 + 0x10) =
                     s_is_not_attached_to_the_previous_w_027cecf0._16_8_;
                *(undefined8 *)(pcVar56 + 0x18) = uVar32;
                uVar32 = s_is_not_attached_to_the_previous_w_027cecf0._8_8_;
                *(undefined8 *)pcVar56 = s_is_not_attached_to_the_previous_w_027cecf0._0_8_;
                *(undefined8 *)(pcVar56 + 8) = uVar32;
                pcVar56[0x2a] = '\0';
                pauVar33 = (undefined1 (*) [16])std::string::append(local_158,(ulong)pcVar56);
                uVar32 = *(undefined8 *)pauVar33[1];
                local_b8 = SUB81(uVar32,0);
                uStack_b7 = (undefined1)((ulong)uVar32 >> 8);
                uStack_b6 = (undefined6)((ulong)uVar32 >> 0x10);
                uVar32 = *(undefined8 *)*pauVar33;
                local_c8 = SUB81(uVar32,0);
                uStack_c7 = (uint)((ulong)uVar32 >> 8);
                cStack_c3 = (char)((ulong)uVar32 >> 0x28);
                cStack_c2 = (char)((ulong)uVar32 >> 0x30);
                cStack_c1 = (char)((ulong)uVar32 >> 0x38);
                AStack_c0 = SUB81(*(undefined8 *)(*pauVar33 + 8),0);
                uStack_bf = (undefined7)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 8);
                *pauVar33 = (undefined1  [16])0x0;
                *(undefined8 *)pauVar33[1] = 0;
                pauVar33 = (undefined1 (*) [16])std::string::append((char *)&local_c8);
                pbVar50 = local_220;
                bVar43 = (*pauVar33)[0];
                bVar2 = (*pauVar33)[1];
                stack0xffffffffffffff20 =
                     (Route *)(CONCAT28(uStack_da,*(undefined8 *)(*pauVar33 + 8)) >> 0x10);
                local_e8._0_8_ = *(undefined8 *)(*pauVar33 + 2);
                uVar32 = *(undefined8 *)pauVar33[1];
                *pauVar33 = (undefined1  [16])0x0;
                *(undefined8 *)pauVar33[1] = 0;
                if ((*local_220 & 1) != 0) {
                  operator_delete(*(void **)(local_220 + 0x10));
                }
                *pbVar50 = bVar43;
                pbVar50[1] = bVar2;
                uVar4 = local_e8._0_8_;
                *(undefined8 *)(local_258 + 6) = local_e8._6_8_;
                *(undefined8 *)local_258 = uVar4;
                *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                if (((byte)local_c8 & 1) != 0) {
                  operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                }
                operator_delete(pcVar56);
                plVar66 = local_200;
                pAVar42 = local_270;
                if (((byte)local_158[0] & 1) == 0) {
                  if (((byte)local_58[0] & 1) != 0) goto LAB_0027e6bd;
LAB_0027e678:
                  AVar69 = local_1d8[0x50];
                }
                else {
                  operator_delete(local_148);
                  if (((byte)local_58[0] & 1) == 0) goto LAB_0027e678;
LAB_0027e6bd:
                  operator_delete(local_48);
                  AVar69 = local_1d8[0x50];
                }
                if (((byte)AVar69 & 1) != 0) {
                  pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                }
                _source_sim_log_write(3,"ATC",
                                  "Unable to parse route \'%s\' (airway not attached to previous waypoint)"
                                  ,pAVar42);
                goto LAB_0027f1df;
              }
              local_c8 = local_248[0];
              uStack_c7 = local_248._1_4_;
              cStack_c3 = local_248[5];
              cStack_c2 = local_248[6];
              cStack_c1 = local_248[7];
              AStack_c0 = local_248[8];
              uStack_bf = local_248._9_7_;
              local_b8 = SUB81(local_338,0);
              uStack_b7 = (undefined1)((ulong)local_338 >> 8);
              uStack_b6 = (undefined6)((ulong)local_338 >> 0x10);
              uStack_b0 = (undefined1)local_340;
              uStack_af = (undefined7)((ulong)local_340 >> 8);
              ATCUtilsGetNavByName
                        (&local_6a0,(string *)(local_1f8 + (long)paVar29),-1,(GeoSegment *)&local_c8
                         ,&local_268);
              local_c8 = local_248[0];
              uStack_c7 = local_248._1_4_;
              cStack_c3 = local_248[5];
              cStack_c2 = local_248[6];
              cStack_c1 = local_248[7];
              AStack_c0 = local_248[8];
              uStack_bf = local_248._9_7_;
              local_b8 = SUB81(local_338,0);
              uStack_b7 = (undefined1)((ulong)local_338 >> 8);
              uStack_b6 = (undefined6)((ulong)local_338 >> 0x10);
              uStack_b0 = (undefined1)local_340;
              uStack_af = (undefined7)((ulong)local_340 >> 8);
              ATCUtilsGetFixByName
                        (&local_6a0,(string *)(local_1f8 + (long)paVar29),(GeoSegment *)&local_c8,
                         (vec_fix_struct **)&local_1a8);
              ATCUtilsGetAptByDisplayID((string *)(local_1f8 + (long)paVar29),&local_280);
              auVar78 = local_58;
              uVar53 = local_208;
              puVar38 = (undefined8 *)CONCAT26(local_1a8._6_2_,(undefined6)local_1a8);
              if ((((local_218 == (awy_node_struct *)0x0 && local_268 == (vec_nav_struct *)0x0) &&
                   puVar38 == (undefined8 *)0x0) && local_280 == (vec_apt_struct *)0x0) &&
                  bVar43 == 1) {
                local_58._1_8_ = 0x7772696120656854;
                local_58[0] = (sub_match)0x16;
                local_58._8_4_ = 0x20796177;
                local_58._13_3_ = auVar78._13_3_;
                local_58[0xc] = 0;
                if ((local_1f8[local_210 * 8] & 1) == 0) {
                  pbVar50 = local_1f8 + local_210 * 8 + 1;
                }
                else {
                  pbVar50 = *(byte **)(local_1f8 + local_210 * 8 + 0x10);
                }
                pauVar33 = (undefined1 (*) [16])std::string::append(local_58,(ulong)pbVar50);
                local_148 = *(char **)pauVar33[1];
                _local_158 = *pauVar33;
                *pauVar33 = (undefined1  [16])0x0;
                *(undefined8 *)pauVar33[1] = 0;
                pcVar56 = operator_new(0x40);
                uVar32 = s_is_not_attached_to_the_previous_f_027ced61._40_8_;
                *(undefined8 *)(pcVar56 + 0x20) =
                     s_is_not_attached_to_the_previous_f_027ced61._32_8_;
                *(undefined8 *)(pcVar56 + 0x28) = uVar32;
                uVar32 = s_is_not_attached_to_the_previous_f_027ced61._24_8_;
                *(undefined8 *)(pcVar56 + 0x10) =
                     s_is_not_attached_to_the_previous_f_027ced61._16_8_;
                *(undefined8 *)(pcVar56 + 0x18) = uVar32;
                uVar32 = s_is_not_attached_to_the_previous_f_027ced61._8_8_;
                *(undefined8 *)pcVar56 = s_is_not_attached_to_the_previous_f_027ced61._0_8_;
                *(undefined8 *)(pcVar56 + 8) = uVar32;
                pcVar56[0x2f] = 'm';
                pcVar56[0x30] = 'p';
                pcVar56[0x31] = 'o';
                pcVar56[0x32] = 'n';
                pcVar56[0x33] = 'e';
                pcVar56[0x34] = 'n';
                pcVar56[0x35] = 't';
                pcVar56[0x36] = ' ';
                pcVar56[0x37] = '\0';
                pauVar33 = (undefined1 (*) [16])std::string::append(local_158,(ulong)pcVar56);
                uVar32 = *(undefined8 *)pauVar33[1];
                local_b8 = SUB81(uVar32,0);
                uStack_b7 = (undefined1)((ulong)uVar32 >> 8);
                uStack_b6 = (undefined6)((ulong)uVar32 >> 0x10);
                uVar32 = *(undefined8 *)*pauVar33;
                local_c8 = SUB81(uVar32,0);
                uStack_c7 = (uint)((ulong)uVar32 >> 8);
                cStack_c3 = (char)((ulong)uVar32 >> 0x28);
                cStack_c2 = (char)((ulong)uVar32 >> 0x30);
                cStack_c1 = (char)((ulong)uVar32 >> 0x38);
                AStack_c0 = SUB81(*(undefined8 *)(*pauVar33 + 8),0);
                uStack_bf = (undefined7)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 8);
                *pauVar33 = (undefined1  [16])0x0;
                *(undefined8 *)pauVar33[1] = 0;
                lVar67 = (long)((int)uVar53 + -1);
                if ((local_1f8[lVar67 * 0x18] & 1) == 0) {
                  pbVar50 = local_1f8 + lVar67 * 0x18 + 1;
                }
                else {
                  pbVar50 = *(byte **)(local_1f8 + lVar67 * 0x18 + 0x10);
                }
                pauVar33 = (undefined1 (*) [16])
                           std::string::append((char *)&local_c8,(ulong)pbVar50);
                pbVar50 = local_220;
                bVar43 = (*pauVar33)[0];
                bVar2 = (*pauVar33)[1];
                stack0xffffffffffffff20 =
                     (Route *)(CONCAT28(uStack_da,*(undefined8 *)(*pauVar33 + 8)) >> 0x10);
                local_e8._0_8_ = *(undefined8 *)(*pauVar33 + 2);
                uVar32 = *(undefined8 *)pauVar33[1];
                *pauVar33 = (undefined1  [16])0x0;
                *(undefined8 *)pauVar33[1] = 0;
                if ((*local_220 & 1) != 0) {
                  operator_delete(*(void **)(local_220 + 0x10));
                }
                *pbVar50 = bVar43;
                pbVar50[1] = bVar2;
                uVar4 = local_e8._0_8_;
                *(undefined8 *)(local_258 + 6) = local_e8._6_8_;
                *(undefined8 *)local_258 = uVar4;
                *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                if (((byte)local_c8 & 1) != 0) {
                  operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                }
                operator_delete(pcVar56);
                plVar66 = local_200;
                pAVar42 = local_270;
                if (((byte)local_158[0] & 1) == 0) {
                  if (((byte)local_58[0] & 1) != 0) goto LAB_0027e3db;
LAB_0027e396:
                  AVar69 = local_1d8[0x50];
                }
                else {
                  operator_delete(local_148);
                  if (((byte)local_58[0] & 1) == 0) goto LAB_0027e396;
LAB_0027e3db:
                  operator_delete(local_48);
                  AVar69 = local_1d8[0x50];
                }
                if (((byte)AVar69 & 1) != 0) {
                  pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                }
                _source_sim_log_write(3,"ATC",
                                  "Unable to parse route \'%s\' (airway not attached to previous comp)"
                                  ,pAVar42);
                goto LAB_0027f1df;
              }
              fVar73 = DAT_0253accc;
              if (puVar38 != (undefined8 *)0x0) {
                dVar76 = (double)(float)*puVar38;
                dVar79 = (double)(float)((ulong)*puVar38 >> 0x20);
                local_c8 = SUB81(dVar76,0);
                uStack_c7 = (uint)((ulong)dVar76 >> 8);
                cStack_c3 = (char)((ulong)dVar76 >> 0x28);
                cStack_c2 = (char)((ulong)dVar76 >> 0x30);
                cStack_c1 = (char)((ulong)dVar76 >> 0x38);
                AStack_c0 = SUB81(dVar79,0);
                uStack_bf = (undefined7)((ulong)dVar79 >> 8);
                fVar73 = (float)ATCGeomDistBetweenLonLatPts
                                          (&local_6a0,(GeoPoint2D *)local_248,
                                           (GeoPoint2D *)&local_c8);
              }
              local_228 = (void *)CONCAT44(local_228._4_4_,fVar73);
              fVar74 = DAT_0253accc;
              if (local_268 != (vec_nav_struct *)0x0) {
                dVar76 = (double)(float)*(undefined8 *)local_268;
                dVar79 = (double)(float)((ulong)*(undefined8 *)local_268 >> 0x20);
                local_c8 = SUB81(dVar76,0);
                uStack_c7 = (uint)((ulong)dVar76 >> 8);
                cStack_c3 = (char)((ulong)dVar76 >> 0x28);
                cStack_c2 = (char)((ulong)dVar76 >> 0x30);
                cStack_c1 = (char)((ulong)dVar76 >> 0x38);
                AStack_c0 = SUB81(dVar79,0);
                uStack_bf = (undefined7)((ulong)dVar79 >> 8);
                fVar74 = (float)ATCGeomDistBetweenLonLatPts
                                          (&local_6a0,(GeoPoint2D *)local_248,
                                           (GeoPoint2D *)&local_c8);
                fVar73 = local_228._0_4_;
              }
              fVar75 = DAT_0253accc;
              if (local_280 != (vec_apt_struct *)0x0) {
                local_2a0 = CONCAT44(local_2a0._4_4_,fVar74);
                auVar78 = **(undefined1 (**) [16])(local_280 + 0x10);
                auVar77._0_8_ = auVar78._8_8_;
                auVar77._8_4_ = auVar78._0_4_;
                auVar77._12_4_ = auVar78._4_4_;
                local_c8 = auVar78[8];
                uStack_c7 = auVar78._9_4_;
                cStack_c3 = auVar78[0xd];
                cStack_c2 = auVar78[0xe];
                cStack_c1 = auVar78[0xf];
                AStack_c0 = auVar78[0];
                uStack_bf = auVar77._9_7_;
                fVar75 = (float)ATCGeomDistBetweenLonLatPts
                                          (&local_6a0,(GeoPoint2D *)local_248,
                                           (GeoPoint2D *)&local_c8);
                fVar73 = local_228._0_4_;
                fVar74 = (float)local_2a0;
              }
              pbVar50 = local_1f8;
              plVar66 = local_200;
              lVar46 = local_210;
              pvVar28 = (vec_fix_struct *)CONCAT26(local_1a8._6_2_,(undefined6)local_1a8);
              if (pvVar28 == (vec_fix_struct *)0x0) {
                pvVar58 = (vec_fix_struct *)0x0;
joined_r0x0027b09d:
                if (local_268 == (vec_nav_struct *)0x0) goto joined_r0x0027b056;
LAB_0027aff0:
                cVar17 = -0x7f;
                if (fVar73 == fVar75) {
                  cVar17 = '\0';
                }
                if (fVar75 < fVar73) {
                  cVar17 = '\x01';
                }
                if (fVar73 < fVar75) {
                  cVar17 = -1;
                }
                fVar10 = fVar75;
                if (cVar17 < '\0') {
                  fVar10 = fVar73;
                }
                if (cVar17 == -0x7f) {
                  fVar10 = fVar75;
                }
                if (fVar10 < fVar74) {
                  local_268 = (vec_nav_struct *)0x0;
                  fVar74 = DAT_0253accc;
                  goto joined_r0x0027b056;
                }
                p_Var48 = (__tree_node *)local_268;
                if (local_280 != (vec_apt_struct *)0x0) goto LAB_0027b0b2;
joined_r0x0027b101:
                pvVar44 = (vec_apt_struct *)0x0;
                if (bVar43 == 0) goto LAB_0027b220;
LAB_0027b129:
                if (((char)local_1d0 != '\0') || (local_218 == (awy_node_struct *)0x0))
                goto LAB_0027b220;
                uVar21 = (int)local_208 + 1;
                pbVar50 = (byte *)(long)(int)uVar21;
                lVar67 = local_210;
                if (((long)pbStack_1f0 - (long)local_1f8 >> 3) * -0x5555555555555555 - (long)pbVar50
                    == 0) {
                  auVar78 = **(undefined1 (**) [16])(local_290 + 0x10);
                  local_e8._0_8_ = auVar78._8_8_;
                  local_e8._8_4_ = auVar78._0_4_;
                  register0x0000120c = auVar78._4_4_;
                  lVar67 = ATCUtilsGetAwyStart(&local_6a0,(string *)(local_1f8 + local_210 * 8),
                                               (GeoPoint2D *)local_e8);
                  auVar78 = local_58;
                  if (lVar67 == 0) {
                    local_58._1_8_ = 0x7772696120656854;
                    local_58[0] = (sub_match)0x16;
                    local_58._8_4_ = 0x20796177;
                    local_58._13_3_ = auVar78._13_3_;
                    local_58[0xc] = 0;
                    if ((local_1f8[lVar46 * 8] & 1) == 0) {
                      pbVar50 = local_1f8 + lVar46 * 8 + 1;
                    }
                    else {
                      pbVar50 = *(byte **)(local_1f8 + lVar46 * 8 + 0x10);
                    }
                    pauVar33 = (undefined1 (*) [16])std::string::append(local_58,(ulong)pbVar50);
                    local_148 = *(char **)pauVar33[1];
                    _local_158 = *pauVar33;
                    *pauVar33 = (undefined1  [16])0x0;
                    *(undefined8 *)pauVar33[1] = 0;
                    pcVar56 = operator_new(0x60);
                    uVar32 = s_is_the_last_airway_in_the_plan_b_027ceddb._72_8_;
                    *(undefined8 *)(pcVar56 + 0x40) =
                         s_is_the_last_airway_in_the_plan_b_027ceddb._64_8_;
                    *(undefined8 *)(pcVar56 + 0x48) = uVar32;
                    uVar32 = s_is_the_last_airway_in_the_plan_b_027ceddb._56_8_;
                    *(undefined8 *)(pcVar56 + 0x30) =
                         s_is_the_last_airway_in_the_plan_b_027ceddb._48_8_;
                    *(undefined8 *)(pcVar56 + 0x38) = uVar32;
                    uVar32 = s_is_the_last_airway_in_the_plan_b_027ceddb._40_8_;
                    *(undefined8 *)(pcVar56 + 0x20) =
                         s_is_the_last_airway_in_the_plan_b_027ceddb._32_8_;
                    *(undefined8 *)(pcVar56 + 0x28) = uVar32;
                    uVar32 = s_is_the_last_airway_in_the_plan_b_027ceddb._24_8_;
                    *(undefined8 *)(pcVar56 + 0x10) =
                         s_is_the_last_airway_in_the_plan_b_027ceddb._16_8_;
                    *(undefined8 *)(pcVar56 + 0x18) = uVar32;
                    uVar32 = s_is_the_last_airway_in_the_plan_b_027ceddb._8_8_;
                    *(undefined8 *)pcVar56 = s_is_the_last_airway_in_the_plan_b_027ceddb._0_8_;
                    *(undefined8 *)(pcVar56 + 8) = uVar32;
                    pcVar56[0x50] = ' ';
                    pcVar56[0x51] = '\0';
                    pauVar33 = (undefined1 (*) [16])std::string::append(local_158,(ulong)pcVar56);
                    uVar32 = *(undefined8 *)pauVar33[1];
                    local_b8 = SUB81(uVar32,0);
                    uStack_b7 = (undefined1)((ulong)uVar32 >> 8);
                    uStack_b6 = (undefined6)((ulong)uVar32 >> 0x10);
                    uVar32 = *(undefined8 *)*pauVar33;
                    local_c8 = SUB81(uVar32,0);
                    uStack_c7 = (uint)((ulong)uVar32 >> 8);
                    cStack_c3 = (char)((ulong)uVar32 >> 0x28);
                    cStack_c2 = (char)((ulong)uVar32 >> 0x30);
                    cStack_c1 = (char)((ulong)uVar32 >> 0x38);
                    AStack_c0 = SUB81(*(undefined8 *)(*pauVar33 + 8),0);
                    uStack_bf = (undefined7)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 8);
                    *pauVar33 = (undefined1  [16])0x0;
                    *(undefined8 *)pauVar33[1] = 0;
                    if (((byte)local_1d8[0x20] & 1) == 0) {
                      psVar47 = local_288 + 1;
                    }
                    else {
                      psVar47 = *(string **)(local_1d8 + 0x30);
                    }
                    pauVar33 = (undefined1 (*) [16])
                               std::string::append((char *)&local_c8,(ulong)psVar47);
                    pbVar50 = local_220;
                    bVar43 = (*pauVar33)[0];
                    bVar2 = (*pauVar33)[1];
                    local_168 = (undefined6)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 0x10);
                    uVar32 = *(undefined8 *)(*pauVar33 + 2);
                    local_170 = SUB81(uVar32,0);
                    uStack_16f = (undefined4)((ulong)uVar32 >> 8);
                    uStack_16b = (undefined1)((ulong)uVar32 >> 0x28);
                    uStack_16a = (undefined2)((ulong)uVar32 >> 0x30);
                    uVar32 = *(undefined8 *)pauVar33[1];
                    *pauVar33 = (undefined1  [16])0x0;
                    *(undefined8 *)pauVar33[1] = 0;
                    if ((*local_220 & 1) != 0) {
                      operator_delete(*(void **)(local_220 + 0x10));
                    }
                    *pbVar50 = bVar43;
                    pbVar50[1] = bVar2;
                    *(ulong *)(local_258 + 6) = CONCAT62(local_168,uStack_16a);
                    *(ulong *)local_258 =
                         CONCAT26(uStack_16a,CONCAT15(uStack_16b,CONCAT41(uStack_16f,local_170)));
                    *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                    if (((byte)local_c8 & 1) != 0) {
                      operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                    }
                    operator_delete(pcVar56);
                    plVar66 = local_200;
                    pAVar42 = local_270;
                    if (((byte)local_158[0] & 1) == 0) {
                      if (((byte)local_58[0] & 1) != 0) goto LAB_0027f2df;
LAB_0027f1b1:
                      AVar69 = local_1d8[0x50];
                    }
                    else {
                      operator_delete(local_148);
                      if (((byte)local_58[0] & 1) == 0) goto LAB_0027f1b1;
LAB_0027f2df:
                      operator_delete(local_48);
                      AVar69 = local_1d8[0x50];
                    }
                    if (((byte)AVar69 & 1) != 0) {
                      pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                    }
                    _source_sim_log_write(3,"ATC",
                                      "Unable to parse route \'%s\' (airway not near destination)",
                                      pAVar42);
                    goto LAB_0027f1df;
                  }
                  local_228 = (void *)CONCAT44(local_228._4_4_,uVar21);
                  pcVar56 = (char *)(*(long *)(lVar67 + 8) + 8);
                  sVar26 = _strlen(pcVar56);
                  if (0xffffffffffffffef < sVar26) {
                    /* WARNING: Subroutine does not return */
                    std::string::__throw_length_error();
                  }
                  local_1d0 = pbVar50;
                  if (sVar26 < 0x17) {
                    local_c8 = (ATCAircraft)((char)SUB81(sVar26,0) * '\x02');
                    puVar31 = &uStack_c7;
                    if (sVar26 != 0) goto LAB_0027bdc4;
                  }
                  else {
                    uVar53 = sVar26 + 0x10 & 0xfffffffffffffff0;
                    puVar31 = operator_new(uVar53);
                    local_b8 = SUB81(puVar31,0);
                    uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                    uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                    local_c8 = (ATCAircraft)((byte)uVar53 | 1);
                    uStack_c7 = (uint)(uVar53 >> 8);
                    cStack_c3 = (char)(uVar53 >> 0x28);
                    cStack_c2 = (char)(uVar53 >> 0x30);
                    cStack_c1 = (char)(uVar53 >> 0x38);
                    uStack_bf = (undefined7)(sVar26 >> 8);
                    AStack_c0 = SUB81(sVar26,0);
LAB_0027bdc4:
                    _memcpy(puVar31,pcVar56,sVar26);
                  }
                  *(undefined1 *)((long)puVar31 + sVar26) = 0;
                  std::vector<std::string,std::allocator<std::string>>::push_back
                            ((vector<std::string,std::allocator<std::string>> *)&local_1f8,
                             (string *)&local_c8);
                  pbVar50 = local_1d0;
                  lVar67 = local_210;
                  uVar21 = (uint)local_228._0_4_;
                  if (((byte)local_c8 & 1) != 0) {
                    operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                  }
                }
                local_c8 = SUB81((list *)&local_c8,0);
                uStack_c7 = (uint)((ulong)&local_c8 >> 8);
                cStack_c3 = (char)((ulong)&local_c8 >> 0x28);
                cStack_c2 = (char)((ulong)&local_c8 >> 0x30);
                cStack_c1 = (char)((ulong)&local_c8 >> 0x38);
                uStack_bf = (undefined7)((ulong)&local_c8 >> 8);
                local_b8 = (ATCAircraft)0x0;
                uStack_b7 = 0;
                uStack_b6 = 0;
                AStack_c0 = local_c8;
                ATCUtilsWalkAwyTo(&local_6a0,(string *)(local_1f8 + lVar67 * 8),
                                  (string *)(local_1f8 + (long)pbVar50 * 0x18),local_218,
                                  (list *)&local_c8);
                lVar67 = CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
                if (lVar67 == 0) {
                  local_d8 = operator_new(0x20);
                  uVar32 = s_We_could_not_link_the_airway_027cee66._21_8_;
                  stack0xffffffffffffff20 = (Route *)_UNK_025206a8;
                  local_e8._0_8_ = _DAT_025206a0;
                  *(ulong *)(local_d8 + 0xd) =
                       CONCAT53(s_We_could_not_link_the_airway_027cee66._16_5_,
                                s_We_could_not_link_the_airway_027cee66._13_3_);
                  *(undefined8 *)(local_d8 + 0x15) = uVar32;
                  uVar32 = CONCAT35(s_We_could_not_link_the_airway_027cee66._13_3_,
                                    s_We_could_not_link_the_airway_027cee66._8_5_);
                  *(undefined8 *)local_d8 = s_We_could_not_link_the_airway_027cee66._0_8_;
                  *(undefined8 *)(local_d8 + 8) = uVar32;
                  local_d8[0x1d] = '\0';
                  if ((local_1f8[local_210 * 8] & 1) == 0) {
                    pbVar34 = local_1f8 + local_210 * 8 + 1;
                  }
                  else {
                    pbVar34 = *(byte **)(local_1f8 + local_210 * 8 + 0x10);
                  }
                  pauVar33 = (undefined1 (*) [16])std::string::append(local_e8,(ulong)pbVar34);
                  local_48 = *(undefined1 **)pauVar33[1];
                  local_58 = *pauVar33;
                  *(undefined8 *)*pauVar33 = 0;
                  *(undefined8 *)(*pauVar33 + 8) = 0;
                  *(undefined8 *)pauVar33[1] = 0;
                  local_170 = (string)0x8;
                  uStack_16f = 0x206f7420;
                  uStack_16b = 0;
                  pauVar33 = (undefined1 (*) [16])std::string::append(local_58,(ulong)&uStack_16f);
                  local_148 = *(char **)pauVar33[1];
                  _local_158 = *pauVar33;
                  *(undefined8 *)*pauVar33 = 0;
                  *(undefined8 *)(*pauVar33 + 8) = 0;
                  *(undefined8 *)pauVar33[1] = 0;
                  if ((local_1f8[(long)pbVar50 * 0x18] & 1) == 0) {
                    pbVar50 = local_1f8 + (long)pbVar50 * 0x18 + 1;
                  }
                  else {
                    pbVar50 = *(byte **)(local_1f8 + (long)pbVar50 * 0x18 + 0x10);
                  }
                  pbVar34 = (byte *)std::string::append(local_158,(ulong)pbVar50);
                  pbVar50 = local_220;
                  bVar43 = *pbVar34;
                  bVar2 = pbVar34[1];
                  local_190 = (undefined6)((ulong)*(undefined8 *)(pbVar34 + 8) >> 0x10);
                  local_198 = (undefined6)*(undefined8 *)(pbVar34 + 2);
                  uStack_192 = (undefined2)((ulong)*(undefined8 *)(pbVar34 + 2) >> 0x30);
                  uVar32 = *(undefined8 *)(pbVar34 + 0x10);
                  pbVar34[0] = 0;
                  pbVar34[1] = 0;
                  pbVar34[2] = 0;
                  pbVar34[3] = 0;
                  pbVar34[4] = 0;
                  pbVar34[5] = 0;
                  pbVar34[6] = 0;
                  pbVar34[7] = 0;
                  pbVar34[8] = 0;
                  pbVar34[9] = 0;
                  pbVar34[10] = 0;
                  pbVar34[0xb] = 0;
                  pbVar34[0xc] = 0;
                  pbVar34[0xd] = 0;
                  pbVar34[0xe] = 0;
                  pbVar34[0xf] = 0;
                  pbVar34[0x10] = 0;
                  pbVar34[0x11] = 0;
                  pbVar34[0x12] = 0;
                  pbVar34[0x13] = 0;
                  pbVar34[0x14] = 0;
                  pbVar34[0x15] = 0;
                  pbVar34[0x16] = 0;
                  pbVar34[0x17] = 0;
                  if ((*local_220 & 1) != 0) {
                    operator_delete(*(void **)(local_220 + 0x10));
                  }
                  *pbVar50 = bVar43;
                  pbVar50[1] = bVar2;
                  *(ulong *)(local_258 + 6) = CONCAT62(local_190,uStack_192);
                  *(ulong *)local_258 = CONCAT26(uStack_192,local_198);
                  *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                  if (((byte)local_158[0] & 1) == 0) {
                    if (((byte)local_170 & 1) != 0) goto LAB_0027c37b;
LAB_0027c225:
                    pAVar42 = local_270;
                    if (((byte)local_58[0] & 1) != 0) goto LAB_0027c391;
LAB_0027c22f:
                    if (((byte)local_e8[0] & 1) != 0) goto LAB_0027c3a7;
LAB_0027c23c:
                    AVar69 = local_1d8[0x50];
                  }
                  else {
                    operator_delete(local_148);
                    if (((byte)local_170 & 1) == 0) goto LAB_0027c225;
LAB_0027c37b:
                    pAVar42 = local_270;
                    operator_delete(local_160);
                    if (((byte)local_58[0] & 1) == 0) goto LAB_0027c22f;
LAB_0027c391:
                    operator_delete(local_48);
                    if (((byte)local_e8[0] & 1) == 0) goto LAB_0027c23c;
LAB_0027c3a7:
                    operator_delete(local_d8);
                    AVar69 = local_1d8[0x50];
                  }
                  if (((byte)AVar69 & 1) != 0) {
                    pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                  }
                  _source_sim_log_write(3,"ATC","Unable to parse route \'%s\' (unlinked airways)",
                                    pAVar42);
                }
                else {
                  pAVar54 = (ATCAircraft *)CONCAT71(uStack_bf,AStack_c0);
                  if (pAVar54 != &local_c8) {
                    do {
                      ATCRouteUtils::AppendIFRAirwaySegment
                                (local_250,*(awy_edge_struct **)(pAVar54 + 0x10),
                                 *(awy_node_struct **)(pAVar54 + 0x18),
                                 (string *)(local_1f8 + (long)paVar29));
                      pAVar54 = *(ATCAircraft **)(pAVar54 + 8);
                    } while (pAVar54 != &local_c8);
                  }
                  pbVar34 = local_1f8;
                  local_218 = *(awy_node_struct **)
                               (CONCAT17(cStack_c1,
                                         CONCAT16(cStack_c2,
                                                  CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))))
                               + 0x18);
                  local_248._8_8_ = (double)(float)((ulong)**(undefined8 **)(local_218 + 8) >> 0x20)
                  ;
                  local_248._0_8_ = (double)(float)**(undefined8 **)(local_218 + 8);
                  lVar46 = *(long *)(local_218 + 8);
                  sVar26 = _strlen((char *)(lVar46 + 8));
                  if ((pbVar34[(long)pbVar50 * 0x18] & 1) == 0) {
                    sVar45 = (size_t)(pbVar34[(long)pbVar50 * 0x18] >> 1);
                  }
                  else {
                    sVar45 = *(size_t *)(pbVar34 + (long)pbVar50 * 0x18 + 8);
                  }
                  if (sVar26 == sVar45) {
                    iVar20 = std::string::compare
                                       ((ulong)(pbVar34 + (long)pbVar50 * 0x18),0,
                                        (char *)0xffffffffffffffff,(ulong)(lVar46 + 8));
                    local_208 = local_208 & 0xffffffff;
                    if (iVar20 == 0) {
                      local_208 = (ulong)uVar21;
                    }
                  }
                }
                if (CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)) != 0) {
                  lVar63 = CONCAT17(cStack_c1,
                                    CONCAT16(cStack_c2,
                                             CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))));
                  lVar46 = *(long *)CONCAT71(uStack_bf,AStack_c0);
                  *(undefined8 *)(lVar46 + 8) = *(undefined8 *)(lVar63 + 8);
                  **(long **)(lVar63 + 8) = lVar46;
                  local_b8 = (ATCAircraft)0x0;
                  uStack_b7 = 0;
                  uStack_b6 = 0;
                  pAVar54 = (ATCAircraft *)CONCAT71(uStack_bf,AStack_c0);
                  while (pAVar54 != &local_c8) {
                    pAVar3 = *(ATCAircraft **)(pAVar54 + 8);
                    operator_delete(pAVar54);
                    pAVar54 = pAVar3;
                  }
                }
                plVar66 = local_200;
                if (lVar67 != 0) goto LAB_0027c2e1;
                goto LAB_0027f1df;
              }
              cVar17 = -0x7f;
              if (fVar74 == fVar75) {
                cVar17 = '\0';
              }
              if (fVar75 < fVar74) {
                cVar17 = '\x01';
              }
              if (fVar74 < fVar75) {
                cVar17 = -1;
              }
              fVar10 = fVar74;
              if (-1 < cVar17) {
                fVar10 = fVar75;
              }
              fVar9 = fVar75;
              if (cVar17 != -0x7f) {
                fVar9 = fVar10;
              }
              pvVar58 = pvVar28;
              if (fVar73 <= fVar9) goto joined_r0x0027b09d;
              local_1a8._0_6_ = 0;
              local_1a8._6_2_ = 0;
              pvVar28 = (vec_fix_struct *)0x0;
              pvVar58 = (vec_fix_struct *)0x0;
              fVar73 = DAT_0253accc;
              if (local_268 != (vec_nav_struct *)0x0) goto LAB_0027aff0;
joined_r0x0027b056:
              p_Var48 = (__tree_node *)0x0;
              if (local_280 == (vec_apt_struct *)0x0) goto joined_r0x0027b101;
LAB_0027b0b2:
              cVar17 = -0x7f;
              if (fVar74 == fVar73) {
                cVar17 = '\0';
              }
              if (fVar73 < fVar74) {
                cVar17 = '\x01';
              }
              if (fVar74 < fVar73) {
                cVar17 = -1;
              }
              fVar10 = fVar73;
              if (cVar17 < '\0') {
                fVar10 = fVar74;
              }
              if (cVar17 == -0x7f) {
                fVar10 = fVar73;
              }
              if (fVar10 < fVar75) {
                local_280 = (vec_apt_struct *)0x0;
                goto joined_r0x0027b101;
              }
              pvVar44 = local_280;
              if (bVar43 != 0) goto LAB_0027b129;
LAB_0027b220:
              if (local_1c8._0_8_ == 0) {
                if (p_Var48 == (__tree_node *)0x0) {
                  if (pvVar58 == (vec_fix_struct *)0x0) {
                    if (pvVar44 == (vec_apt_struct *)0x0) {
                      cVar17 = ATCUtilsLatLonStringToFloat
                                         ((string *)(paVar29 + (long)local_1f8),&local_2d0,
                                          &local_2cc);
                      if (cVar17 == '\0') {
                        local_c8 = (ATCAircraft)0x20;
                        uStack_c7 = (uint)s_Unknown_navaid__027cf033._0_8_;
                        cStack_c3 = SUB81(s_Unknown_navaid__027cf033._0_8_,4);
                        cStack_c2 = SUB81(s_Unknown_navaid__027cf033._0_8_,5);
                        cStack_c1 = SUB81(s_Unknown_navaid__027cf033._0_8_,6);
                        AStack_c0 = SUB81(s_Unknown_navaid__027cf033._0_8_,7);
                        uStack_bf = (undefined7)s_Unknown_navaid__027cf033._8_8_;
                        local_b8 = SUB81(s_Unknown_navaid__027cf033._8_8_,7);
                        uStack_b7 = 0;
                        if ((local_1f8[local_210 * 8] & 1) == 0) {
                          pbVar50 = local_1f8 + local_210 * 8 + 1;
                        }
                        else {
                          pbVar50 = *(byte **)(local_1f8 + local_210 * 8 + 0x10);
                        }
                        pauVar33 = (undefined1 (*) [16])
                                   std::string::append((char *)&local_c8,(ulong)pbVar50);
                        pbVar50 = local_220;
                        bVar43 = (*pauVar33)[0];
                        bVar2 = (*pauVar33)[1];
                        stack0xfffffffffffffeb0 =
                             (long)(CONCAT28(uStack_14a,*(undefined8 *)(*pauVar33 + 8)) >> 0x10);
                        local_158._0_8_ = *(undefined8 *)(*pauVar33 + 2);
                        uVar32 = *(undefined8 *)pauVar33[1];
                        *pauVar33 = (undefined1  [16])0x0;
                        *(undefined8 *)pauVar33[1] = 0;
                        if ((*local_220 & 1) != 0) {
                          operator_delete(*(void **)(local_220 + 0x10));
                        }
                        *pbVar50 = bVar43;
                        pbVar50[1] = bVar2;
                        uVar4 = local_158._0_8_;
                        *(undefined8 *)(local_258 + 6) = local_158._6_8_;
                        *(undefined8 *)local_258 = uVar4;
                        *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                        if (((byte)local_c8 & 1) == 0) {
                          if (((byte)local_1d8[0x50] & 1) == 0) goto LAB_0027f41f;
LAB_0027f3e0:
                          pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                          if ((local_1f8[local_210 * 8] & 1) == 0) goto LAB_0027f433;
LAB_0027f3f8:
                          pbVar50 = *(byte **)(local_1f8 + local_210 * 8 + 0x10);
                        }
                        else {
                          operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                          if (((byte)local_1d8[0x50] & 1) != 0) goto LAB_0027f3e0;
LAB_0027f41f:
                          pAVar42 = local_270;
                          if ((local_1f8[local_210 * 8] & 1) != 0) goto LAB_0027f3f8;
LAB_0027f433:
                          pbVar50 = local_1f8 + local_210 * 8 + 1;
                        }
                        _source_sim_log_write(3,"ATC",
                                          "Unable to parse route \'%s\' (unknown navaid \'%s\')",
                                          pAVar42,pbVar50);
                        goto LAB_0027f1df;
                      }
                      auVar78 = insertps(ZEXT416((uint)local_2d0),local_2cc,0x10);
                      local_248._8_8_ = (double)auVar78._4_4_;
                      local_248._0_8_ = (double)auVar78._0_4_;
                      local_c8 = (ATCAircraft)0xa;
                      cStack_c3 = 'T';
                      uStack_c7 = 0x504f4547;
                      cStack_c2 = '\0';
                      ATCRouteUtils::AppendIFRFakePt
                                (local_250,(GeoPoint2D *)local_248,(string *)&local_c8);
                      if (((byte)local_c8 & 1) != 0) {
                        operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                      }
                      local_218 = (awy_node_struct *)0x0;
                    }
                    else {
                      auVar78 = **(undefined1 (**) [16])(pvVar44 + 0x10);
                      local_248._0_8_ = auVar78._8_8_;
                      local_248._8_4_ = auVar78._0_4_;
                      local_248._12_4_ = auVar78._4_4_;
                      ATCRouteUtils::AppendIFRAptAsWpt(local_250,pvVar44,1);
                      local_218 = (awy_node_struct *)ATCUtilsAirwayNodeFromApt(&local_6a0,local_280)
                      ;
                    }
                  }
                  else {
                    local_248._8_8_ = (double)(float)((ulong)*(undefined8 *)pvVar28 >> 0x20);
                    local_248._0_8_ = (double)(float)*(undefined8 *)pvVar28;
                    local_c8 = (ATCAircraft)0x0;
                    uStack_c7 = 0;
                    cStack_c3 = '\0';
                    cStack_c2 = '\0';
                    cStack_c1 = '\0';
                    AStack_c0 = (ATCAircraft)0x0;
                    uStack_bf = 0;
                    local_b8 = (ATCAircraft)0x0;
                    uStack_b7 = 0;
                    uStack_b6 = 0;
                    ATCRouteUtils::AppendIFRFix(local_250,pvVar58,(string *)&local_c8);
                    if (((byte)local_c8 & 1) != 0) {
                      operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                    }
                    local_218 = (awy_node_struct *)
                                ATCUtilsAirwayNodeFromFix
                                          (&local_6a0,
                                           (vec_fix_struct *)
                                           CONCAT26(local_1a8._6_2_,(undefined6)local_1a8));
                  }
                }
                else {
                  local_248._8_8_ = (double)(float)((ulong)*(undefined8 *)local_268 >> 0x20);
                  local_248._0_8_ = (double)(float)*(undefined8 *)local_268;
                  local_c8 = (ATCAircraft)0x0;
                  uStack_c7 = 0;
                  cStack_c3 = '\0';
                  cStack_c2 = '\0';
                  cStack_c1 = '\0';
                  AStack_c0 = (ATCAircraft)0x0;
                  uStack_bf = 0;
                  local_b8 = (ATCAircraft)0x0;
                  uStack_b7 = 0;
                  uStack_b6 = 0;
                  ATCRouteUtils::AppendIFRNavaid
                            (local_250,(vec_nav_struct *)p_Var48,(string *)&local_c8);
                  if (((byte)local_c8 & 1) != 0) {
                    operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                  }
                  local_218 = (awy_node_struct *)ATCUtilsAirwayNodeFromNavaid(&local_6a0,local_268);
                }
              }
              else {
                if ((int)local_208 == 0) {
                  local_148 = operator_new(0x30);
                  uVar32 = s_We_can_t_start_with_the_VOR_radi_027ceeb2._24_8_;
                  stack0xfffffffffffffeb0 = _UNK_02520a18;
                  local_158._0_8_ = _DAT_02520a10;
                  *(undefined8 *)(local_148 + 0x10) =
                       s_We_can_t_start_with_the_VOR_radi_027ceeb2._16_8_;
                  *(undefined8 *)(local_148 + 0x18) = uVar32;
                  uVar32 = s_We_can_t_start_with_the_VOR_radi_027ceeb2._8_8_;
                  *(undefined8 *)local_148 = s_We_can_t_start_with_the_VOR_radi_027ceeb2._0_8_;
                  *(undefined8 *)(local_148 + 8) = uVar32;
                  local_148[0x1f] = 'i';
                  local_148[0x20] = 'a';
                  local_148[0x21] = 'l';
                  local_148[0x22] = ' ';
                  local_148[0x23] = '\0';
                  if ((local_1f8[local_210 * 8] & 1) == 0) {
                    pbVar50 = local_1f8 + local_210 * 8 + 1;
                  }
                  else {
                    pbVar50 = *(byte **)(local_1f8 + local_210 * 8 + 0x10);
                  }
                  pauVar33 = (undefined1 (*) [16])std::string::append(local_158,(ulong)pbVar50);
                  uVar32 = *(undefined8 *)pauVar33[1];
                  local_b8 = SUB81(uVar32,0);
                  uStack_b7 = (undefined1)((ulong)uVar32 >> 8);
                  uStack_b6 = (undefined6)((ulong)uVar32 >> 0x10);
                  uVar32 = *(undefined8 *)*pauVar33;
                  local_c8 = SUB81(uVar32,0);
                  uStack_c7 = (uint)((ulong)uVar32 >> 8);
                  cStack_c3 = (char)((ulong)uVar32 >> 0x28);
                  cStack_c2 = (char)((ulong)uVar32 >> 0x30);
                  cStack_c1 = (char)((ulong)uVar32 >> 0x38);
                  AStack_c0 = SUB81(*(undefined8 *)(*pauVar33 + 8),0);
                  uStack_bf = (undefined7)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 8);
                  *pauVar33 = (undefined1  [16])0x0;
                  *(undefined8 *)pauVar33[1] = 0;
                  pcVar56 = operator_new(0x30);
                  uVar32 = s_Start_with_a_fix_or_the_VOR_itse_027ceed6._24_8_;
                  *(undefined8 *)(pcVar56 + 0x10) =
                       s_Start_with_a_fix_or_the_VOR_itse_027ceed6._16_8_;
                  *(undefined8 *)(pcVar56 + 0x18) = uVar32;
                  uVar32 = s_Start_with_a_fix_or_the_VOR_itse_027ceed6._8_8_;
                  *(undefined8 *)pcVar56 = s_Start_with_a_fix_or_the_VOR_itse_027ceed6._0_8_;
                  *(undefined8 *)(pcVar56 + 8) = uVar32;
                  pcVar56[0x20] = 'e';
                  pcVar56[0x21] = 'l';
                  pcVar56[0x22] = 'f';
                  pcVar56[0x23] = '.';
                  pcVar56[0x24] = '\0';
                  pauVar33 = (undefined1 (*) [16])
                             std::string::append((char *)&local_c8,(ulong)pcVar56);
                  pbVar50 = local_220;
                  bVar43 = (*pauVar33)[0];
                  bVar2 = (*pauVar33)[1];
                  local_58._8_8_ =
                       (undefined8)
                       (CONCAT28(local_58._14_2_,*(undefined8 *)(*pauVar33 + 8)) >> 0x10);
                  local_58._0_8_ = *(undefined8 *)(*pauVar33 + 2);
                  uVar32 = *(undefined8 *)pauVar33[1];
                  *pauVar33 = (undefined1  [16])0x0;
                  *(undefined8 *)pauVar33[1] = 0;
                  if ((*local_220 & 1) != 0) {
                    operator_delete(*(void **)(local_220 + 0x10));
                  }
                  *pbVar50 = bVar43;
                  pbVar50[1] = bVar2;
                  uVar4 = local_58._0_8_;
                  *(undefined8 *)(local_258 + 6) = local_58._6_8_;
                  *(undefined8 *)local_258 = uVar4;
                  *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                  operator_delete(pcVar56);
                  if (((byte)local_c8 & 1) == 0) {
                    if (((byte)local_158[0] & 1) != 0) goto LAB_0027e893;
LAB_0027e83d:
                    AVar69 = local_1d8[0x50];
                    pAVar42 = local_270;
                    plVar66 = local_200;
                  }
                  else {
                    operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                    if (((byte)local_158[0] & 1) == 0) goto LAB_0027e83d;
LAB_0027e893:
                    plVar66 = local_200;
                    pAVar42 = local_270;
                    operator_delete(local_148);
                    AVar69 = local_1d8[0x50];
                  }
                  if (((byte)AVar69 & 1) != 0) {
                    pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                  }
                  _source_sim_log_write(3,"ATC","Unable to parse route \'%s\' (begins with VOR radial)",
                                    pAVar42);
                  goto LAB_0027f1df;
                }
                if (((long)pbStack_1f0 - (long)local_1f8 >> 3) * -0x5555555555555555 + -1 == lVar67)
                {
                  local_148 = operator_new(0x30);
                  uVar32 = s_We_can_t_end_with_the_VOR_radial_027cef2f._24_8_;
                  stack0xfffffffffffffeb0 = _UNK_02520918;
                  local_158._0_8_ = _DAT_02520910;
                  *(undefined8 *)(local_148 + 0x10) =
                       s_We_can_t_end_with_the_VOR_radial_027cef2f._16_8_;
                  *(undefined8 *)(local_148 + 0x18) = uVar32;
                  uVar32 = s_We_can_t_end_with_the_VOR_radial_027cef2f._8_8_;
                  *(undefined8 *)local_148 = s_We_can_t_end_with_the_VOR_radial_027cef2f._0_8_;
                  *(undefined8 *)(local_148 + 8) = uVar32;
                  local_148[0x20] = ' ';
                  local_148[0x21] = '\0';
                  if ((pbVar50[local_210 * 8] & 1) == 0) {
                    pbVar50 = pbVar50 + local_210 * 8 + 1;
                  }
                  else {
                    pbVar50 = *(byte **)(pbVar50 + local_210 * 8 + 0x10);
                  }
                  pauVar33 = (undefined1 (*) [16])std::string::append(local_158,(ulong)pbVar50);
                  uVar32 = *(undefined8 *)pauVar33[1];
                  local_b8 = SUB81(uVar32,0);
                  uStack_b7 = (undefined1)((ulong)uVar32 >> 8);
                  uStack_b6 = (undefined6)((ulong)uVar32 >> 0x10);
                  uVar32 = *(undefined8 *)*pauVar33;
                  local_c8 = SUB81(uVar32,0);
                  uStack_c7 = (uint)((ulong)uVar32 >> 8);
                  cStack_c3 = (char)((ulong)uVar32 >> 0x28);
                  cStack_c2 = (char)((ulong)uVar32 >> 0x30);
                  cStack_c1 = (char)((ulong)uVar32 >> 0x38);
                  AStack_c0 = SUB81(*(undefined8 *)(*pauVar33 + 8),0);
                  uStack_bf = (undefined7)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 8);
                  *pauVar33 = (undefined1  [16])0x0;
                  *(undefined8 *)pauVar33[1] = 0;
                  pcVar56 = operator_new(0x30);
                  uVar32 = s_End_the_route_with_a_fix_or_the_V_027cef51._36_8_;
                  *(ulong *)(pcVar56 + 0x1c) =
                       CONCAT44(s_End_the_route_with_a_fix_or_the_V_027cef51._32_4_,
                                s_End_the_route_with_a_fix_or_the_V_027cef51._28_4_);
                  *(undefined8 *)(pcVar56 + 0x24) = uVar32;
                  uVar32 = CONCAT44(s_End_the_route_with_a_fix_or_the_V_027cef51._28_4_,
                                    s_End_the_route_with_a_fix_or_the_V_027cef51._24_4_);
                  *(undefined8 *)(pcVar56 + 0x10) =
                       s_End_the_route_with_a_fix_or_the_V_027cef51._16_8_;
                  *(undefined8 *)(pcVar56 + 0x18) = uVar32;
                  uVar32 = s_End_the_route_with_a_fix_or_the_V_027cef51._8_8_;
                  *(undefined8 *)pcVar56 = s_End_the_route_with_a_fix_or_the_V_027cef51._0_8_;
                  *(undefined8 *)(pcVar56 + 8) = uVar32;
                  pcVar56[0x2c] = '\0';
                  pauVar33 = (undefined1 (*) [16])
                             std::string::append((char *)&local_c8,(ulong)pcVar56);
                  pbVar50 = local_220;
                  bVar43 = (*pauVar33)[0];
                  bVar2 = (*pauVar33)[1];
                  local_58._8_8_ =
                       (undefined8)
                       (CONCAT28(local_58._14_2_,*(undefined8 *)(*pauVar33 + 8)) >> 0x10);
                  local_58._0_8_ = *(undefined8 *)(*pauVar33 + 2);
                  uVar32 = *(undefined8 *)pauVar33[1];
                  *pauVar33 = (undefined1  [16])0x0;
                  *(undefined8 *)pauVar33[1] = 0;
                  if ((*local_220 & 1) != 0) {
                    operator_delete(*(void **)(local_220 + 0x10));
                  }
                  *pbVar50 = bVar43;
                  pbVar50[1] = bVar2;
                  uVar4 = local_58._0_8_;
                  *(undefined8 *)(local_258 + 6) = local_58._6_8_;
                  *(undefined8 *)local_258 = uVar4;
                  *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                  operator_delete(pcVar56);
                  if (((byte)local_c8 & 1) == 0) {
                    if (((byte)local_158[0] & 1) != 0) goto LAB_0027ea12;
LAB_0027e9bc:
                    AVar69 = local_1d8[0x50];
                    pAVar42 = local_270;
                    plVar66 = local_200;
                  }
                  else {
                    operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                    if (((byte)local_158[0] & 1) == 0) goto LAB_0027e9bc;
LAB_0027ea12:
                    plVar66 = local_200;
                    pAVar42 = local_270;
                    operator_delete(local_148);
                    AVar69 = local_1d8[0x50];
                  }
                  if (((byte)AVar69 & 1) != 0) {
                    pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                  }
                  _source_sim_log_write(3,"ATC","Unable to parse route \'%s\' (ends with VOR radial)",
                                    pAVar42);
                  goto LAB_0027f1df;
                }
                pcVar56 = (char *)(local_1c8._0_8_ + 8);
                sVar26 = _strlen(pcVar56);
                if (0xffffffffffffffef < sVar26) {
                    /* WARNING: Subroutine does not return */
                  std::string::__throw_length_error();
                }
                if (sVar26 < 0x17) {
                  local_c8 = (ATCAircraft)((char)SUB81(sVar26,0) * '\x02');
                  puVar31 = &uStack_c7;
                  if (sVar26 != 0) goto LAB_0027b358;
                }
                else {
                  uVar53 = sVar26 + 0x10 & 0xfffffffffffffff0;
                  puVar31 = operator_new(uVar53);
                  local_b8 = SUB81(puVar31,0);
                  uStack_b7 = (undefined1)((ulong)puVar31 >> 8);
                  uStack_b6 = (undefined6)((ulong)puVar31 >> 0x10);
                  local_c8 = (ATCAircraft)((byte)uVar53 | 1);
                  uStack_c7 = (uint)(uVar53 >> 8);
                  cStack_c3 = (char)(uVar53 >> 0x28);
                  cStack_c2 = (char)(uVar53 >> 0x30);
                  cStack_c1 = (char)(uVar53 >> 0x38);
                  uStack_bf = (undefined7)(sVar26 >> 8);
                  AStack_c0 = SUB81(sVar26,0);
LAB_0027b358:
                  _memcpy(puVar31,pcVar56,sVar26);
                }
                AVar14 = local_c8;
                *(undefined1 *)((long)puVar31 + sVar26) = 0;
                sVar26 = (ulong)((byte)local_c8 >> 1);
                if (((byte)local_c8 & 1) != 0) {
                  sVar26 = CONCAT71(uStack_bf,AStack_c0);
                }
                lVar67 = (long)((int)local_208 + -1);
                bVar43 = local_1f8[lVar67 * 0x18];
                if ((bVar43 & 1) == 0) {
                  if (sVar26 == bVar43 >> 1) goto LAB_0027b3ca;
LAB_0027bab1:
                  cVar17 = ATCUtilsFixIsOnRadial(&local_6a0,local_1c8,(GeoPoint2D *)local_248);
                  if (((byte)AVar14 & 1) != 0) {
                    operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                  }
                  iVar20 = (int)local_208;
                  if (cVar17 == '\0') {
                    local_58._1_8_ = 0x20524f5620656854;
                    local_58[0] = (sub_match)0x1e;
                    local_58._8_8_ = 0x206c616964617220;
                    local_48 = (undefined1 *)((ulong)local_48 & 0xffffffffffffff00);
                    if ((local_1f8[local_210 * 8] & 1) == 0) {
                      pbVar50 = local_1f8 + local_210 * 8 + 1;
                    }
                    else {
                      pbVar50 = *(byte **)(local_1f8 + local_210 * 8 + 0x10);
                    }
                    pauVar33 = (undefined1 (*) [16])std::string::append(local_58,(ulong)pbVar50);
                    local_148 = *(char **)pauVar33[1];
                    _local_158 = *pauVar33;
                    *pauVar33 = (undefined1  [16])0x0;
                    *(undefined8 *)pauVar33[1] = 0;
                    pcVar56 = operator_new(0x30);
                    uVar32 = s_is_not_connected_to_the_previous_027cefb0._24_8_;
                    *(undefined8 *)(pcVar56 + 0x10) =
                         s_is_not_connected_to_the_previous_027cefb0._16_8_;
                    *(undefined8 *)(pcVar56 + 0x18) = uVar32;
                    uVar32 = s_is_not_connected_to_the_previous_027cefb0._8_8_;
                    *(undefined8 *)pcVar56 = s_is_not_connected_to_the_previous_027cefb0._0_8_;
                    *(undefined8 *)(pcVar56 + 8) = uVar32;
                    pcVar56[0x20] = 's';
                    pcVar56[0x21] = ' ';
                    pcVar56[0x22] = 'p';
                    pcVar56[0x23] = 'o';
                    pcVar56[0x24] = 'i';
                    pcVar56[0x25] = 'n';
                    pcVar56[0x26] = 't';
                    pcVar56[0x27] = ' ';
                    pcVar56[0x28] = '\0';
                    pauVar33 = (undefined1 (*) [16])std::string::append(local_158,(ulong)pcVar56);
                    uVar32 = *(undefined8 *)pauVar33[1];
                    local_b8 = SUB81(uVar32,0);
                    uStack_b7 = (undefined1)((ulong)uVar32 >> 8);
                    uStack_b6 = (undefined6)((ulong)uVar32 >> 0x10);
                    uVar32 = *(undefined8 *)*pauVar33;
                    local_c8 = SUB81(uVar32,0);
                    uStack_c7 = (uint)((ulong)uVar32 >> 8);
                    cStack_c3 = (char)((ulong)uVar32 >> 0x28);
                    cStack_c2 = (char)((ulong)uVar32 >> 0x30);
                    cStack_c1 = (char)((ulong)uVar32 >> 0x38);
                    AStack_c0 = SUB81(*(undefined8 *)(*pauVar33 + 8),0);
                    uStack_bf = (undefined7)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 8);
                    *pauVar33 = (undefined1  [16])0x0;
                    *(undefined8 *)pauVar33[1] = 0;
                    if ((local_1f8[lVar67 * 0x18] & 1) == 0) {
                      pbVar50 = local_1f8 + lVar67 * 0x18 + 1;
                    }
                    else {
                      pbVar50 = *(byte **)(local_1f8 + lVar67 * 0x18 + 0x10);
                    }
                    pauVar33 = (undefined1 (*) [16])
                               std::string::append((char *)&local_c8,(ulong)pbVar50);
                    pbVar50 = local_220;
                    bVar43 = (*pauVar33)[0];
                    bVar2 = (*pauVar33)[1];
                    stack0xffffffffffffff20 =
                         (Route *)(CONCAT28(uStack_da,*(undefined8 *)(*pauVar33 + 8)) >> 0x10);
                    local_e8._0_8_ = *(undefined8 *)(*pauVar33 + 2);
                    uVar32 = *(undefined8 *)pauVar33[1];
                    *pauVar33 = (undefined1  [16])0x0;
                    *(undefined8 *)pauVar33[1] = 0;
                    if ((*local_220 & 1) != 0) {
                      operator_delete(*(void **)(local_220 + 0x10));
                    }
                    *pbVar50 = bVar43;
                    pbVar50[1] = bVar2;
                    uVar4 = local_e8._0_8_;
                    *(undefined8 *)(local_258 + 6) = local_e8._6_8_;
                    *(undefined8 *)local_258 = uVar4;
                    *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                    if (((byte)local_c8 & 1) != 0) {
                      operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                    }
                    operator_delete(pcVar56);
                    plVar66 = local_200;
                    pAVar42 = local_270;
                    if (((byte)local_158[0] & 1) == 0) {
                      if (((byte)local_58[0] & 1) != 0) goto LAB_0027ebfa;
LAB_0027ebb5:
                      AVar69 = local_1d8[0x50];
                    }
                    else {
                      operator_delete(local_148);
                      if (((byte)local_58[0] & 1) == 0) goto LAB_0027ebb5;
LAB_0027ebfa:
                      operator_delete(local_48);
                      AVar69 = local_1d8[0x50];
                    }
                    if (((byte)AVar69 & 1) != 0) {
                      pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                    }
                    _source_sim_log_write(3,"ATC",
                                      "Unable to parse route \'%s\' (disconnected VOR radial)",
                                      pAVar42);
                    goto LAB_0027f1df;
                  }
                }
                else {
                  if (sVar26 != *(size_t *)(local_1f8 + lVar67 * 0x18 + 8)) goto LAB_0027bab1;
LAB_0027b3ca:
                  if ((bVar43 & 1) == 0) {
                    pbVar50 = local_1f8 + lVar67 * 0x18 + 1;
                  }
                  else {
                    pbVar50 = *(byte **)(local_1f8 + lVar67 * 0x18 + 0x10);
                  }
                  pvVar24 = (void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
                  if (((byte)local_c8 & 1) == 0) {
                    if (sVar26 != 0) {
                      uVar53 = 0;
                      do {
                        if (*(byte *)((long)&uStack_c7 + uVar53) != pbVar50[uVar53])
                        goto LAB_0027bab1;
                        uVar53 = uVar53 + 1;
                      } while ((byte)local_c8 >> 1 != uVar53);
                    }
                  }
                  else {
                    if ((sVar26 != 0) && (iVar20 = _memcmp(pvVar24,pbVar50,sVar26), iVar20 != 0))
                    goto LAB_0027bab1;
                    operator_delete(pvVar24);
                  }
                  iVar20 = (int)local_208;
                }
                local_e8._0_12_ = ZEXT812(0);
                iVar20 = iVar20 + 1;
                local_228 = (void *)CONCAT44(local_228._4_4_,iVar20);
                local_1d0 = (byte *)((long)iVar20 * 3);
                lVar67 = (long)iVar20 * 0x18;
                local_218 = paVar29;
                pvVar27 = (vec_nav_struct *)
                          ATCFindNavaidForRadial
                                    (&local_6a0,local_1c8,(string *)(local_1f8 + lVar67));
                pvVar28 = (vec_fix_struct *)
                          ATCFindFixForRadial(&local_6a0,local_1c8,(string *)(local_1f8 + lVar67));
                paVar29 = (awy_node_struct *)
                          ATCFindAirwayForRadial
                                    (&local_6a0,local_1c8,(string *)(local_1f8 + lVar67));
                cVar17 = ATCUtilsParseVORRadial
                                   (&local_6a0,(string *)(local_1f8 + lVar67),
                                    (GeoPoint2D *)local_248,local_e8);
                if (cVar17 == '\0') {
                  auVar7._8_8_ = 0;
                  auVar7._0_8_ = stack0xffffffffffffff20;
                  _local_e8 = auVar7 << 0x40;
                }
                if (pvVar28 != (vec_fix_struct *)0x0) {
                  if (paVar29 != (awy_node_struct *)0x0) goto LAB_0027bc4c;
LAB_0027bc93:
                  if (pvVar28 != (vec_fix_struct *)0x0) {
                    paVar30 = (awy_node_struct *)ATCUtilsAirwayNodeFromFix(&local_6a0,pvVar28);
                    goto joined_r0x0027bcaa;
                  }
LAB_0027bd35:
                  if (pvVar27 != (vec_nav_struct *)0x0) {
                    paVar30 = (awy_node_struct *)ATCUtilsAirwayNodeFromNavaid(&local_6a0,pvVar27);
                    goto LAB_0027bd49;
                  }
LAB_0027ec12:
                  local_58._1_8_ = 0x20524f5620656854;
                  local_58[0] = (sub_match)0x1e;
                  local_58._8_8_ = 0x206c616964617220;
                  local_48 = (undefined1 *)((ulong)local_48 & 0xffffffffffffff00);
                  if ((local_1f8[local_210 * 8] & 1) == 0) {
                    pbVar50 = local_1f8 + local_210 * 8 + 1;
                  }
                  else {
                    pbVar50 = *(byte **)(local_1f8 + local_210 * 8 + 0x10);
                  }
                  pauVar33 = (undefined1 (*) [16])std::string::append(local_58,(ulong)pbVar50);
                  local_148 = *(char **)pauVar33[1];
                  _local_158 = *pauVar33;
                  *pauVar33 = (undefined1  [16])0x0;
                  *(undefined8 *)pauVar33[1] = 0;
                  pcVar56 = operator_new(0x30);
                  uVar32 = s_is_not_connected_to_the_next_poi_027cf00e._24_8_;
                  *(undefined8 *)(pcVar56 + 0x10) =
                       s_is_not_connected_to_the_next_poi_027cf00e._16_8_;
                  *(undefined8 *)(pcVar56 + 0x18) = uVar32;
                  uVar32 = s_is_not_connected_to_the_next_poi_027cf00e._8_8_;
                  *(undefined8 *)pcVar56 = s_is_not_connected_to_the_next_poi_027cf00e._0_8_;
                  *(undefined8 *)(pcVar56 + 8) = uVar32;
                  pcVar56[0x20] = 'i';
                  pcVar56[0x21] = 'n';
                  pcVar56[0x22] = 't';
                  pcVar56[0x23] = ' ';
                  pcVar56[0x24] = '\0';
                  pauVar33 = (undefined1 (*) [16])std::string::append(local_158,(ulong)pcVar56);
                  uVar32 = *(undefined8 *)pauVar33[1];
                  local_b8 = SUB81(uVar32,0);
                  uStack_b7 = (undefined1)((ulong)uVar32 >> 8);
                  uStack_b6 = (undefined6)((ulong)uVar32 >> 0x10);
                  uVar32 = *(undefined8 *)*pauVar33;
                  local_c8 = SUB81(uVar32,0);
                  uStack_c7 = (uint)((ulong)uVar32 >> 8);
                  cStack_c3 = (char)((ulong)uVar32 >> 0x28);
                  cStack_c2 = (char)((ulong)uVar32 >> 0x30);
                  cStack_c1 = (char)((ulong)uVar32 >> 0x38);
                  AStack_c0 = SUB81(*(undefined8 *)(*pauVar33 + 8),0);
                  uStack_bf = (undefined7)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 8);
                  *pauVar33 = (undefined1  [16])0x0;
                  *(undefined8 *)pauVar33[1] = 0;
                  if ((local_1f8[(long)local_1d0 * 8] & 1) == 0) {
                    pbVar50 = local_1f8 + (long)local_1d0 * 8 + 1;
                  }
                  else {
                    pbVar50 = *(byte **)(local_1f8 + (long)local_1d0 * 8 + 0x10);
                  }
                  pauVar33 = (undefined1 (*) [16])
                             std::string::append((char *)&local_c8,(ulong)pbVar50);
                  pbVar50 = local_220;
                  bVar43 = (*pauVar33)[0];
                  bVar2 = (*pauVar33)[1];
                  local_168 = (undefined6)((ulong)*(undefined8 *)(*pauVar33 + 8) >> 0x10);
                  uVar32 = *(undefined8 *)(*pauVar33 + 2);
                  local_170 = SUB81(uVar32,0);
                  uStack_16f = (undefined4)((ulong)uVar32 >> 8);
                  uStack_16b = (undefined1)((ulong)uVar32 >> 0x28);
                  uStack_16a = (undefined2)((ulong)uVar32 >> 0x30);
                  uVar32 = *(undefined8 *)pauVar33[1];
                  *pauVar33 = (undefined1  [16])0x0;
                  *(undefined8 *)pauVar33[1] = 0;
                  if ((*local_220 & 1) != 0) {
                    operator_delete(*(void **)(local_220 + 0x10));
                  }
                  *pbVar50 = bVar43;
                  pbVar50[1] = bVar2;
                  *(ulong *)(local_258 + 6) = CONCAT62(local_168,uStack_16a);
                  *(ulong *)local_258 =
                       CONCAT26(uStack_16a,CONCAT15(uStack_16b,CONCAT41(uStack_16f,local_170)));
                  *(undefined8 *)(pbVar50 + 0x10) = uVar32;
                  if (((byte)local_c8 & 1) != 0) {
                    operator_delete((void *)CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8)));
                  }
                  operator_delete(pcVar56);
                  plVar66 = local_200;
                  pAVar42 = local_270;
                  if (((byte)local_158[0] & 1) == 0) {
                    if (((byte)local_58[0] & 1) != 0) goto LAB_0027eff3;
LAB_0027efae:
                    AVar69 = local_1d8[0x50];
                  }
                  else {
                    operator_delete(local_148);
                    if (((byte)local_58[0] & 1) == 0) goto LAB_0027efae;
LAB_0027eff3:
                    operator_delete(local_48);
                    AVar69 = local_1d8[0x50];
                  }
                  if (((byte)AVar69 & 1) != 0) {
                    pAVar42 = *(ATCAircraftFlightPlan **)(local_1d8 + 0x60);
                  }
                  _source_sim_log_write(3,"ATC","Unable to parse route \'%s\' (disconnected VOR radial)"
                                    ,pAVar42);
                  goto LAB_0027f1df;
                }
                if (local_e8._0_8_ == 0) {
                  if (paVar29 == (awy_node_struct *)0x0) goto LAB_0027bd35;
LAB_0027bd06:
                  pvVar28 = (vec_fix_struct *)ATCUtilsFixFromAirwayNode(&local_6a0,paVar29);
                }
                else {
                  pvVar28 = (vec_fix_struct *)ATCFindFixForRadialPair(&local_6a0,local_1c8,local_e8)
                  ;
                  if (paVar29 == (awy_node_struct *)0x0) goto LAB_0027bc93;
LAB_0027bc4c:
                  if (pvVar28 == (vec_fix_struct *)0x0) goto LAB_0027bd06;
                }
                paVar30 = paVar29;
                if (pvVar27 == (vec_nav_struct *)0x0) {
                  pvVar27 = (vec_nav_struct *)ATCUtilsNavaidFromAirwayNode(&local_6a0,paVar29);
joined_r0x0027bcaa:
                  if (pvVar27 != (vec_nav_struct *)0x0) goto LAB_0027bd49;
                  if (pvVar28 == (vec_fix_struct *)0x0) goto LAB_0027ec12;
                  local_248._8_8_ = (double)(float)((ulong)*(undefined8 *)pvVar28 >> 0x20);
                  local_248._0_8_ = (double)(float)*(undefined8 *)pvVar28;
                  ATCRouteUtils::AppendIFRFix
                            (local_250,pvVar28,(string *)(local_218 + (long)local_1f8));
                  uVar23 = (int)local_208;
                  if (local_e8._0_8_ == 0 && paVar29 == (awy_node_struct *)0x0) {
                    uVar23 = local_228._0_4_;
                  }
                  local_228 = (void *)CONCAT44(local_228._4_4_,uVar23);
                }
                else {
LAB_0027bd49:
                  local_248._8_8_ = (double)(float)((ulong)*(undefined8 *)pvVar27 >> 0x20);
                  local_248._0_8_ = (double)(float)*(undefined8 *)pvVar27;
                  ATCRouteUtils::AppendIFRNavaid
                            (local_250,pvVar27,(string *)(local_218 + (long)local_1f8));
                }
                local_208 = (ulong)local_228 & 0xffffffff;
                plVar66 = local_200;
                local_218 = paVar30;
              }
LAB_0027c2e1:
              pAVar35 = (ATCWaypoint *)ATCFlightRoute::GetEnd(local_250);
              if ((pAVar35 != (ATCWaypoint *)0x0) &&
                 (lVar67 = ATCWaypoint::GetPrevPt(pAVar35), lVar67 != 0)) {
                pGVar36 = (GeoPoint2D *)ATCWaypoint::GetGeoCoords(pAVar35);
                this_00 = (ATCWaypoint *)ATCWaypoint::GetPrevPt(pAVar35);
                pGVar37 = (GeoPoint2D *)ATCWaypoint::GetGeoCoords(this_00);
                cVar17 = ATCGeomAreGeoPtsColocated(&local_6a0,pGVar36,pGVar37);
                if (cVar17 != '\0') {
                  pAVar35 = (ATCWaypoint *)ATCWaypoint::GetPrevPt(pAVar35);
                  ATCFlightRoute::TrimAfter(local_250,pAVar35);
                }
              }
            }
          }
          else if (*(long *)(local_1f8 + uVar53 * 0x18 + 8) != 0) goto LAB_0027a67a;
LAB_0027a610:
          uVar21 = (int)local_208 + 1;
          local_208 = (ulong)uVar21;
          uVar53 = (ulong)(int)uVar21;
          uVar25 = ((long)pbStack_1f0 - (long)local_1f8 >> 3) * -0x5555555555555555;
        } while (uVar53 <= uVar25 && uVar25 - uVar53 != 0);
      }
      cVar17 = (**(code **)(*(long *)local_278 + 0x420))();
      if (cVar17 == '\0') {
        if (((byte)local_1d8[0x70] & 1) == 0) {
          uVar53 = (ulong)((byte)local_1d8[0x70] >> 1);
          if (uVar53 != 0) goto LAB_0027e097;
LAB_0027e0cb:
          if (((byte)local_1d8[0x88] & 1) == 0) {
            uVar53 = (ulong)((byte)local_1d8[0x88] >> 1);
          }
          else {
            uVar53 = *(ulong *)(local_1d8 + 0x90);
          }
          if ((uVar53 == 0) ||
             ((uVar53 == 0xc &&
              (iVar20 = std::string::compare
                                  ((ulong)local_2a8,0,(char *)0xffffffffffffffff,0x27ca661),
              iVar20 == 0)))) goto LAB_0027df9d;
        }
        else {
          uVar53 = *(ulong *)(local_1d8 + 0x78);
          if (uVar53 == 0) goto LAB_0027e0cb;
LAB_0027e097:
          if ((uVar53 == 0xc) &&
             (iVar20 = std::string::compare((ulong)local_298,0,(char *)0xffffffffffffffff,0x27ca661)
             , iVar20 == 0)) goto LAB_0027e0cb;
        }
        std::string::assign((char *)local_220);
LAB_0027f1df:
        local_208 = 0;
      }
      else {
LAB_0027df9d:
        pAVar54 = local_278;
        if (local_278[0x1b8] == (ATCAircraft)0x0) {
          uVar53 = ATCAircraftFlightPlan::ATCAircraftFlightPlan
                             ((ATCAircraftFlightPlan *)(local_278 + 0x110),local_1d8);
          pAVar54[0x1b8] = (ATCAircraft)0x1;
        }
        else {
          *(long *)(local_278 + 0x110) = *(long *)local_1d8;
          std::string::operator=((string *)(local_278 + 0x118),local_2c8);
          std::string::operator=((string *)(pAVar54 + 0x130),local_288);
          std::string::operator=((string *)(pAVar54 + 0x148),(string *)(local_1d8 + 0x38));
          std::string::operator=((string *)(pAVar54 + 0x160),local_2c0);
          pAVar54[0x17c] = *(ATCAircraft *)(local_1d8 + 0x6c);
          *(undefined4 *)(pAVar54 + 0x178) = *(undefined4 *)(local_1d8 + 0x68);
          std::string::operator=((string *)(pAVar54 + 0x180),local_298);
          std::string::operator=((string *)(pAVar54 + 0x198),local_2a8);
          pAVar54[0x1b4] = *(ATCAircraft *)(local_1d8 + 0xa4);
          uVar53 = (ulong)*(uint *)(local_1d8 + 0xa0);
          *(uint *)(pAVar54 + 0x1b0) = *(uint *)(local_1d8 + 0xa0);
        }
        *(undefined4 *)(pAVar54 + 0x114) = 1;
        local_208 = CONCAT71((int7)(uVar53 >> 8),1);
      }
LAB_0027f1e8:
      ATCFlightRoute::FinishEdit(local_250,true);
      goto joined_r0x00279bf4;
    }
    if (((byte)local_1d8[0x20] & 1) == 0) {
      psVar47 = local_288 + 1;
      pcVar56 = "Arrival airport \'%s\' is a seaport; you can only fly into airports.";
    }
    else {
      psVar47 = *(string **)(local_1d8 + 0x30);
      pcVar56 = "Arrival airport \'%s\' is a seaport; you can only fly into airports.";
    }
  }
  stl_printf((char *)&local_c8,pcVar56,psVar47);
  pbVar50 = local_220;
  if ((*local_220 & 1) != 0) {
    operator_delete(*(void **)(local_220 + 0x10));
  }
  *(ulong *)(pbVar50 + 0x10) = CONCAT62(uStack_b6,CONCAT11(uStack_b7,local_b8));
  *(ulong *)pbVar50 =
       CONCAT17(cStack_c1,CONCAT16(cStack_c2,CONCAT15(cStack_c3,CONCAT41(uStack_c7,local_c8))));
  *(ulong *)(pbVar50 + 8) = CONCAT71(uStack_bf,AStack_c0);
  local_208 = 0;
joined_r0x00279bf4:
  if (plVar66 != (long *)0x0) {
    LOCK();
    plVar6 = plVar66 + 1;
    lVar67 = *plVar6;
    *plVar6 = *plVar6 + -1;
    UNLOCK();
    if (lVar67 == 0) {
      (**(code **)(*plVar66 + 0x10))(plVar66);
      std::__shared_weak_count::__release_weak();
    }
  }
  std::__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>>::destroy
            ((__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>> *)
             &local_358,local_350);
  std::__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>>::destroy
            ((__tree<runway_spec_t,std::less<runway_spec_t>,std::allocator<runway_spec_t>> *)
             &local_320,local_318);
  pbVar50 = local_1f8;
  uVar53 = local_208;
  pbVar34 = pbStack_1f0;
  if (local_1f8 != (byte *)0x0) {
    while (pbVar49 = pbVar34, pbVar49 != pbVar50) {
      pbVar34 = pbVar49 + -0x18;
      if ((pbVar49[-0x18] & 1) != 0) {
        operator_delete(*(void **)(pbVar49 + -8));
      }
    }
    pbStack_1f0 = pbVar50;
    operator_delete(local_1f8);
  }
  if (*(long *)PTR____stack_chk_guard_02ac0540 != lStack_38) {
                    /* WARNING: Subroutine does not return */
    ___stack_chk_fail();
  }
  return uVar53 & 0xffffffff;
}


// 00281d50  ATCAircraft::SetFlightInfo

/* ATCAircraft::SetFlightInfo(ATCAircraftFlightInfo const&) */

undefined8 __thiscall ATCAircraft::SetFlightInfo(ATCAircraft *this,ATCAircraftFlightInfo *param_1)

{
  std::string::operator=((string *)(this + 0x200),(string *)param_1);
  std::string::operator=((string *)(this + 0x218),(string *)(param_1 + 0x18));
  std::string::operator=((string *)(this + 0x230),(string *)(param_1 + 0x30));
  *(undefined4 *)(this + 0x248) = *(undefined4 *)(param_1 + 0x48);
  std::string::operator=((string *)(this + 0x250),(string *)(param_1 + 0x50));
  return 1;
}


// 0028f8c0  ATCSourceAircraft::MinutesUntilDescent

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* ATCSourceAircraft::MinutesUntilDescent(units::value<float, units::scale<units::units::m, 1, 1852>
   >&, units::value<float, units::scale<units::scale<units::scale<units::units::m, 100, 1>, 100,
   254>, 1, 12> >&, ATCTransitionLayer const&, std::optional<units::value<float,
   units::scale<units::scale<units::scale<units::units::m, 100, 1>, 100, 254>, 1, 12> > >&) const */

void ATCSourceAircraft::MinutesUntilDescent
               (value *param_1,value *param_2,ATCTransitionLayer *param_3,optional *param_4)

{
  undefined8 uVar1;
  undefined8 *puVar2;
  int iVar3;
  UTL_geoid *pUVar4;
  long lVar5;
  ATCWaypoint *pAVar6;
  vec_apt_struct *pvVar7;
  GeoPoint2D *pGVar8;
  ATCFlightSegment *pAVar9;
  __tree_node_base *p_Var10;
  long *plVar11;
  long *plVar12;
  ATCWaypoint *pAVar13;
  long lVar14;
  char cVar15;
  char cVar16;
  undefined8 *puVar17;
  float *pfVar18;
  undefined8 *puVar19;
  long *plVar20;
  float *in_R8;
  undefined4 uVar21;
  float fVar22;
  float fVar23;
  undefined8 extraout_XMM0_Qb;
  undefined1 auVar24 [16];
  undefined1 auVar25 [16];
  undefined1 auVar26 [16];
  undefined1 auVar27 [16];
  undefined8 extraout_XMM0_Qb_01;
  undefined1 auVar28 [16];
  undefined1 auVar29 [16];
  float in_XMM1_Da;
  undefined4 in_XMM1_Db;
  long local_b8;
  long lStack_b0;
  int *local_a8;
  float *local_a0;
  UTL_geoid *local_98;
  long *local_90;
  long *local_88;
  long *local_80;
  float local_78;
  float local_74;
  float local_70 [2];
  optional *local_68;
  undefined8 local_60;
  float local_58;
  undefined4 local_54;
  long *local_50;
  undefined1 local_48 [16];
  undefined8 local_38;
  undefined8 extraout_XMM0_Qb_00;
  
  local_a0 = in_R8;
  local_68 = param_4;
  pUVar4 = (UTL_geoid *)REN_geoid::instance();
  *(undefined4 *)param_2 = 0xbf800000;
  *(undefined4 *)param_3 = 0xc4cd766d;
  lVar5 = ATCFlightRoute::GetStart(*(ATCFlightRoute **)(param_1 + 0x60));
  if (lVar5 == 0) {
    local_a8 = (int *)0x0;
    iVar3 = *(int *)(param_1 + 0x68);
  }
  else {
    pAVar6 = (ATCWaypoint *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(param_1 + 0x60));
    local_a8 = (int *)ATCWaypoint::GetNextSeg(pAVar6);
    iVar3 = *(int *)(param_1 + 0x68);
  }
  if (iVar3 != 2) {
    return;
  }
  if (*(int *)(param_1 + 0x6c) != 1) {
    return;
  }
  if (local_a8 == (int *)0x0) {
    return;
  }
  if (*local_a8 == 5) {
    iVar3 = local_a8[1];
  }
  else {
    if (*local_a8 != 3) {
      return;
    }
    iVar3 = local_a8[3];
  }
  if (iVar3 == 2) {
    return;
  }
  local_58 = (float)DAT_02525350;
  lVar5 = ATCFlightRoute::GetStart(*(ATCFlightRoute **)(param_1 + 0x60));
  if (lVar5 == 0) {
    return;
  }
  pAVar6 = (ATCWaypoint *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(param_1 + 0x60));
  pAVar6 = (ATCWaypoint *)ATCWaypoint::GetNextPt(pAVar6);
  if (pAVar6 == (ATCWaypoint *)0x0) {
    return;
  }
  *(undefined4 *)param_3 = 0;
  pvVar7 = (vec_apt_struct *)apt_from_id((string *)(param_1 + 0x88));
  uVar21 = DAT_025246b8;
  if (pvVar7 != (vec_apt_struct *)0x0) {
    in_XMM1_Db = 0;
    in_XMM1_Da = ((*(float *)(pvVar7 + 0x48) * DAT_02525330 * DAT_02525330) / DAT_02536f14) /
                 DAT_02536f10;
    *(float *)param_3 = in_XMM1_Da;
    iVar3 = ATCUtilsAptControlType(pvVar7);
    uVar21 = *(undefined4 *)(&DAT_0253c1a8 + (ulong)(iVar3 == 0) * 4);
  }
  local_38 = (long *)CONCAT44(local_38._4_4_,uVar21);
  local_50 = (long *)(**(code **)(*(long *)param_1 + 0x268))(param_1);
  auVar24 = local_48;
  local_48._4_4_ = in_XMM1_Db;
  local_48._0_4_ = in_XMM1_Da;
  local_48._8_8_ = auVar24._8_8_;
  pGVar8 = (GeoPoint2D *)ATCWaypoint::GetGeoCoords(pAVar6);
  local_98 = pUVar4;
  uVar21 = ATCGeomDistBetweenLonLatPts(pUVar4,(GeoPoint2D *)&local_50,pGVar8);
  *(undefined4 *)param_2 = uVar21;
  pAVar9 = (ATCFlightSegment *)ATCWaypoint::GetNextSeg(pAVar6);
  local_54 = (undefined4)CONCAT71((int7)((ulong)pAVar9 >> 8),1);
  uVar1 = local_60;
  while (pAVar9 != (ATCFlightSegment *)0x0) {
    local_60._4_4_ = (undefined4)((ulong)uVar1 >> 0x20);
    if ((pAVar9[0xc0] != (ATCFlightSegment)0x0) && (pAVar9[0xe0] != (ATCFlightSegment)0x0)) {
      *(float *)param_3 =
           ((*(float *)(pAVar9 + 0xbc) * DAT_02525330 * DAT_02525330) / DAT_02536f14) / DAT_02536f10
      ;
      local_38 = (long *)((ulong)local_38 & 0xffffffff00000000);
      if (*(int *)(pAVar9 + 0xb8) == 3) {
        fVar22 = (float)ATCFlightSegment::GetLength(pAVar9);
        *(float *)param_2 = fVar22 + *(float *)param_2;
      }
      local_54 = 0;
      break;
    }
    local_60 = uVar1;
    fVar22 = (float)ATCFlightSegment::GetLength(pAVar9);
    *(float *)param_2 = fVar22 + *(float *)param_2;
    pAVar9 = (ATCFlightSegment *)ATCFlightSegment::GetNextSeg(pAVar9);
    uVar1 = local_60;
  }
  local_74 = (float)(**(code **)(*(long *)param_1 + 0x250))(param_1);
  if ((local_74 == 0.0) && (!NAN(local_74))) {
    return;
  }
  local_60 = CONCAT44(local_60._4_4_,
                      ((DAT_0253bf48 * (float)local_38 * DAT_02536f1c * DAT_02525330 * DAT_02525330)
                      / DAT_02536f14) / DAT_02536f10 + *(float *)param_3);
  fVar22 = (float)(**(code **)(*(long *)param_1 + 0x300))(param_1,3,0);
  fVar22 = fVar22 * *(float *)(param_1 + 0x1e4) * DAT_0253bed8;
  local_58 = *(float *)param_2 - (float)local_38;
  *(float *)param_2 = local_58;
  auVar24._0_8_ = (**(code **)(*(long *)param_1 + 0x2d0))(param_1,1);
  auVar24._8_8_ = extraout_XMM0_Qb;
  auVar24 = insertps(auVar24,fVar22,0x10);
  auVar25._0_4_ = auVar24._0_4_ * _DAT_02536ec0 * _DAT_02536ec0;
  auVar25._4_4_ = auVar24._4_4_ * _UNK_02536ec4 * _UNK_02536ec4;
  auVar25._8_4_ = auVar24._8_4_ * _UNK_02536ec8 * _UNK_02536ec8;
  auVar25._12_4_ = auVar24._12_4_ * _UNK_02536ecc * _UNK_02536ecc;
  auVar24 = divps(auVar25,_DAT_02536ed0);
  auVar24 = divps(auVar24,_DAT_02536ee0);
  local_58 = (((((local_58 * auVar24._4_4_ + (float)local_60) - auVar24._0_4_) / auVar24._4_4_) /
              local_74) / DAT_02536f20) / DAT_02520bc0;
  if (0.0 < local_58) {
    return;
  }
  local_48 = ZEXT816(0);
  local_50 = (long *)local_48;
  if (ATCController::kPossibleStepDescentAlts != (undefined8 *)&DAT_0315e218) {
    local_38 = (long *)0x0;
    plVar12 = (long *)local_48;
    puVar17 = ATCController::kPossibleStepDescentAlts;
LAB_0028fdc4:
    do {
      puVar19 = puVar17;
      plVar11 = plVar12 + 1;
      if (local_38 == (long *)0x0) {
        plVar12 = (long *)local_48;
        plVar11 = (long *)local_48;
      }
LAB_0028fdd8:
      if (*plVar11 == 0) {
        p_Var10 = operator_new(0x20);
        *(undefined4 *)(p_Var10 + 0x1c) = *(undefined4 *)((long)puVar19 + 0x1c);
        *(undefined8 *)p_Var10 = 0;
        *(undefined8 *)(p_Var10 + 8) = 0;
        *(long **)(p_Var10 + 0x10) = plVar12;
        *plVar11 = (long)p_Var10;
        if ((long *)*local_50 != (long *)0x0) {
          local_50 = (long *)*local_50;
          p_Var10 = (__tree_node_base *)*plVar11;
        }
        std::__tree_balance_after_insert<std::__tree_node_base<void*>*>
                  ((__tree_node_base *)local_48._0_8_,p_Var10);
        local_48._8_8_ = local_48._8_8_ + 1;
        puVar2 = (undefined8 *)puVar19[1];
        if ((undefined8 *)puVar19[1] != (undefined8 *)0x0) goto LAB_0028fe40;
LAB_0028fe4d:
        puVar17 = (undefined8 *)puVar19[2];
        if ((undefined8 *)*puVar17 != puVar19) {
          do {
            puVar19 = (undefined8 *)puVar19[2];
            puVar17 = (undefined8 *)puVar19[2];
          } while ((undefined8 *)*puVar17 != puVar19);
        }
      }
      else {
        puVar2 = (undefined8 *)puVar19[1];
        if ((undefined8 *)puVar19[1] == (undefined8 *)0x0) goto LAB_0028fe4d;
LAB_0028fe40:
        do {
          puVar17 = puVar2;
          puVar2 = (undefined8 *)*puVar17;
        } while ((undefined8 *)*puVar17 != (undefined8 *)0x0);
      }
      if (puVar17 == (undefined8 *)&DAT_0315e218) goto LAB_0028fe80;
      local_38 = (long *)local_48._0_8_;
      plVar12 = (long *)local_48;
    } while (local_50 == plVar12);
    plVar11 = (long *)local_48._0_8_;
    if ((long *)local_48._0_8_ == (long *)0x0) {
      plVar12 = &local_38;
      if (puRam0000000000000000 == local_48) {
        plVar12 = &local_38;
        do {
          lVar5 = *plVar12;
          plVar12 = (long *)(lVar5 + 0x10);
        } while (**(long **)(lVar5 + 0x10) == lVar5);
      }
      plVar12 = (long *)*plVar12;
    }
    else {
      do {
        plVar12 = plVar11;
        plVar11 = (long *)plVar12[1];
      } while ((long *)plVar12[1] != (long *)0x0);
    }
    fVar22 = *(float *)((long)plVar12 + 0x1c);
    fVar23 = *(float *)((long)puVar17 + 0x1c);
    cVar15 = -0x7f;
    if (fVar22 == fVar23) {
      cVar15 = '\0';
    }
    if (fVar23 < fVar22) {
      cVar15 = '\x01';
    }
    if (fVar22 < fVar23) {
      cVar15 = -1;
    }
    if ((cVar15 != -0x7f) && (cVar15 < '\0')) goto LAB_0028fdc4;
    plVar12 = (long *)local_48;
    plVar20 = (long *)local_48._0_8_;
    while (puVar19 = puVar17, plVar11 = plVar12, plVar20 != (long *)0x0) {
      while( true ) {
        plVar12 = plVar20;
        fVar22 = *(float *)((long)plVar12 + 0x1c);
        cVar15 = -0x7f;
        if (fVar23 == fVar22) {
          cVar15 = '\0';
        }
        cVar16 = cVar15;
        if (fVar22 < fVar23) {
          cVar16 = '\x01';
        }
        if (fVar23 < fVar22) {
          cVar16 = -1;
        }
        if ((cVar16 != -0x7f) && (cVar16 < '\0')) break;
        if (fVar23 < fVar22) {
          cVar15 = '\x01';
        }
        if (fVar22 < fVar23) {
          cVar15 = -1;
        }
        if ((cVar15 == -0x7f) || (-1 < cVar15)) goto LAB_0028fdd8;
        plVar11 = plVar12 + 1;
        plVar20 = (long *)plVar12[1];
        if ((long *)plVar12[1] == (long *)0x0) goto LAB_0028fdd8;
      }
      plVar20 = (long *)*plVar12;
    }
    goto LAB_0028fdd8;
  }
LAB_0028fe80:
  auVar26._0_8_ =
       (**(code **)(*(long *)param_1 + 0x2c0))
                 (((*(float *)param_3 * DAT_02536f10 * DAT_02536f14) / DAT_02525330) / DAT_02525330,
                  param_1);
  auVar26._8_8_ = extraout_XMM0_Qb_00;
  auVar27._4_12_ = auVar26._4_12_;
  auVar27._0_4_ =
       (((float)auVar26._0_8_ * DAT_02525330 * DAT_02525330) / DAT_02536f14) / DAT_02536f10;
  uVar21 = 0;
  fVar22 = DAT_02520bec;
  fVar23 = (float)ATCUtilsMassageAlt(auVar27._0_8_,0);
  local_38._0_4_ = fVar23;
  local_70[0] = fVar23;
  if ((long *)local_48._0_8_ == (long *)0x0) {
    plVar20 = (long *)local_48;
    plVar11 = plVar20;
    fVar23 = fVar22;
  }
  else {
    plVar12 = (long *)local_48._0_8_;
    plVar11 = (long *)local_48;
    do {
      while( true ) {
        plVar20 = plVar12;
        fVar22 = *(float *)((long)plVar20 + 0x1c);
        uVar21 = 0;
        cVar15 = -0x7f;
        if (fVar23 == fVar22) {
          cVar15 = '\0';
        }
        cVar16 = cVar15;
        if (fVar22 < fVar23) {
          cVar16 = '\x01';
        }
        if (fVar23 < fVar22) {
          cVar16 = -1;
        }
        if ((cVar16 != -0x7f) && (cVar16 < '\0')) break;
        uVar21 = 0;
        if (fVar23 < fVar22) {
          cVar15 = '\x01';
        }
        if (fVar22 < fVar23) {
          cVar15 = -1;
        }
        if ((cVar15 == -0x7f) || (-1 < cVar15)) goto LAB_0028ff8d;
        plVar12 = (long *)plVar20[1];
        plVar11 = plVar20 + 1;
        if ((long *)plVar20[1] == (long *)0x0) goto LAB_0028ff8d;
      }
      plVar12 = (long *)*plVar20;
      plVar11 = plVar20;
    } while ((long *)*plVar20 != (long *)0x0);
  }
LAB_0028ff8d:
  if (*plVar11 == 0) {
    p_Var10 = operator_new(0x20);
    *(float *)(p_Var10 + 0x1c) = (float)local_38;
    *(undefined8 *)p_Var10 = 0;
    *(undefined8 *)(p_Var10 + 8) = 0;
    *(long **)(p_Var10 + 0x10) = plVar20;
    *plVar11 = (long)p_Var10;
    if ((long *)*local_50 != (long *)0x0) {
      local_50 = (long *)*local_50;
      p_Var10 = (__tree_node_base *)*plVar11;
    }
    std::__tree_balance_after_insert<std::__tree_node_base<void*>*>
              ((__tree_node_base *)local_48._0_8_,p_Var10);
    local_48._8_8_ = local_48._8_8_ + 1;
  }
  plVar11 = (long *)std::
                    __lower_bound<std::__less<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>,units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>>&,std::__tree_const_iterator<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>,std::__tree_node<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>,void*>*,long>,units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>>
                              (local_50,local_48,local_70,&local_90);
  fVar22 = (float)(**(code **)(*(long *)param_1 + 0x2c8))(param_1);
  local_90 = (long *)CONCAT44(local_90._4_4_,fVar22 + _DAT_0253bf4c);
  plVar12 = (long *)std::
                    __upper_bound<std::__less<units::value<float,units::units::m>,units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>>&,std::__tree_const_iterator<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>,std::__tree_node<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>,void*>*,long>,units::value<float,units::units::m>>
                              (plVar11,local_48,&local_90,&local_b8);
  if (plVar11 == (long *)local_48) {
    cVar15 = *(char *)(local_a0 + 1);
    goto LAB_002902c8;
  }
  if (plVar12 != plVar11) {
    plVar20 = (long *)*plVar12;
    if ((long *)*plVar12 == (long *)0x0) {
      for (; *(long **)plVar12[2] == plVar12; plVar12 = (long *)plVar12[2]) {
      }
      plVar11 = (long *)plVar12[2];
    }
    else {
      do {
        plVar11 = plVar20;
        plVar20 = (long *)plVar11[1];
      } while ((long *)plVar11[1] != (long *)0x0);
    }
  }
  lVar5 = ATCFlightRoute::GetStart(*(ATCFlightRoute **)(param_1 + 0x60));
  if (lVar5 == 0) {
    pAVar9 = (ATCFlightSegment *)0x0;
  }
  else {
    pAVar6 = (ATCWaypoint *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(param_1 + 0x60));
    pAVar9 = (ATCFlightSegment *)ATCWaypoint::GetNextSeg(pAVar6);
  }
  pAVar6 = (ATCWaypoint *)ATCFlightSegment::GetDstPt(pAVar9);
  local_38 = (long *)(**(code **)(*(long *)param_1 + 0x268))(param_1);
  local_60 = CONCAT44(uVar21,fVar23);
  plVar12 = (long *)ATCWaypoint::GetGeoCoords(pAVar6);
  local_b8 = *plVar12;
  lStack_b0 = plVar12[1];
  local_90 = operator_new(0x20);
  local_88 = local_90 + 4;
  *local_90 = (long)local_38;
  local_90[1] = local_60;
  local_90[2] = local_b8;
  local_90[3] = lStack_b0;
  local_80 = local_88;
  fVar22 = (float)ATCUtilsGetMSAForRouteGeoPts(local_98,&local_90,1);
  local_38._0_4_ = fVar22;
  if (local_90 != (long *)0x0) {
    local_88 = local_90;
    operator_delete(local_90);
  }
  pAVar13 = (ATCWaypoint *)ATCFlightRoute::GetEnd(*(ATCFlightRoute **)(param_1 + 0x60));
  auVar28._0_8_ = ATCUtilsGetMSAForRoute(local_98,pAVar6,pAVar13,false);
  auVar28._8_8_ = extraout_XMM0_Qb_01;
  fVar22 = (float)auVar28._0_8_;
  cVar15 = -0x7f;
  if ((float)local_38 == fVar22) {
    cVar15 = '\0';
  }
  cVar16 = '\x01';
  if ((float)local_38 <= fVar22) {
    cVar16 = cVar15;
  }
  cVar15 = -1;
  if (fVar22 <= (float)local_38) {
    cVar15 = cVar16;
  }
  if (-1 < cVar15) {
    auVar28 = ZEXT416((uint)(float)local_38);
  }
  if (cVar15 == -0x7f) {
    auVar28 = ZEXT416((uint)(float)local_38);
  }
  auVar29._4_12_ = auVar28._4_12_;
  auVar29._0_4_ = ((auVar28._0_4_ * DAT_02536f10 * DAT_02536f14) / DAT_02525330) / DAT_02525330;
  fVar22 = (float)(**(code **)(*(long *)param_1 + 0x2c0))(auVar29._0_8_,param_1);
  switch(*local_a8) {
  case 3:
    if (local_a8[3] != 2) goto switchD_00290208_caseD_4;
    break;
  case 4:
  case 8:
switchD_00290208_caseD_4:
    local_38._0_4_ = ((fVar22 * DAT_02525330 * DAT_02525330) / DAT_02536f14) / DAT_02536f10;
    lVar5 = _lroundf();
    lVar14 = _lroundf();
    if (lVar5 <= lVar14) break;
    local_78 = (float)ATCUtilsConformCruiseAltToDirectionRules(param_1,0);
    goto LAB_00290266;
  case 5:
    if ((local_a8[1] != 2) && (local_a8[0x20] == -2)) goto switchD_00290208_caseD_4;
  }
  local_78 = (float)ATCUtilsMassageAlt(1);
LAB_00290266:
  fVar22 = *(float *)((long)plVar11 + 0x1c);
  cVar15 = -0x7f;
  if (local_78 == fVar22) {
    cVar15 = '\0';
  }
  cVar16 = '\x01';
  if (fVar22 <= local_78) {
    cVar16 = cVar15;
  }
  cVar15 = -1;
  if (local_78 <= fVar22) {
    cVar15 = cVar16;
  }
  pfVar18 = &local_78;
  if (-1 < cVar15) {
    pfVar18 = (float *)((long)plVar11 + 0x1c);
  }
  if (cVar15 == -0x7f) {
    pfVar18 = (float *)((long)plVar11 + 0x1c);
  }
  cVar15 = *(char *)(local_a0 + 1);
  *local_a0 = *pfVar18;
  if (cVar15 == '\0') {
    *(undefined1 *)(local_a0 + 1) = 1;
    cVar15 = '\x01';
  }
LAB_002902c8:
  if (((char)local_54 == '\x01' && cVar15 != '\0') &&
     (fVar22 = *local_a0, *(float *)(local_68 + 4) <= fVar22)) {
    fVar23 = *(float *)(local_68 + 8);
    cVar15 = -0x7f;
    if (fVar22 == fVar23) {
      cVar15 = '\0';
    }
    cVar16 = '\x01';
    if (fVar22 <= fVar23) {
      cVar16 = cVar15;
    }
    cVar15 = -1;
    if (fVar23 <= fVar22) {
      cVar15 = cVar16;
    }
    if ((cVar15 != -0x7f) && (cVar15 < '\0')) {
      *local_a0 = fVar23;
    }
  }
  std::
  __tree<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>,std::less<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>>,std::allocator<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>>>
  ::destroy((__tree<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>,std::less<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>>,std::allocator<units::value<float,units::scale<units::scale<units::scale<units::units::m,100,1>,100,254>,1,12>>>>
             *)&local_50,(__tree_node *)local_48._0_8_);
  return;
}


// 00294d80  ATC_TEXT_hdlr_flightNum

/* ATC_TEXT_hdlr_flightNum(safe_handle<ATCVoice*, &(void UTL_art_asset_retain<ATCVoice>(ATCVoice*)),
   &(void UTL_art_asset_release<ATCVoice>(ATCVoice*))> const&, std::vector<std::string,
   std::allocator<std::string > > const&, std::string&) */

bool ATC_TEXT_hdlr_flightNum(safe_handle *param_1,vector *param_2,string *param_3)

{
  bool bVar1;
  
  bVar1 = *(long *)(param_2 + 8) - (long)*(string **)param_2 == 0x18;
  if (bVar1) {
    std::string::operator=(param_3,*(string **)param_2);
  }
  return bVar1;
}


// 00298d60  ATC_WAVE_hdlr_flightNum

/* ATC_WAVE_hdlr_flightNum(safe_handle<ATCVoice*, &(void UTL_art_asset_retain<ATCVoice>(ATCVoice*)),
   &(void UTL_art_asset_release<ATCVoice>(ATCVoice*))> const&, std::vector<std::string,
   std::allocator<std::string > > const&, std::string&) */

undefined8 ATC_WAVE_hdlr_flightNum(safe_handle *param_1,vector *param_2,string *param_3)

{
  undefined8 uVar1;
  undefined2 local_48;
  undefined6 uStack_46;
  undefined8 uStack_40;
  undefined8 local_38;
  string local_30 [16];
  void *local_20;
  
  uVar1 = 0;
  if (*(long *)(param_2 + 8) - (long)*(string **)param_2 == 0x18) {
    std::string::string(local_30,*(string **)param_2);
    ConvertWordToAliases(&local_48,local_30,1);
    if (((byte)*param_3 & 1) != 0) {
      operator_delete(*(void **)(param_3 + 0x10));
    }
    *(undefined8 *)(param_3 + 0x10) = local_38;
    *(ulong *)param_3 = CONCAT62(uStack_46,local_48);
    *(undefined8 *)(param_3 + 8) = uStack_40;
    local_48 = 0;
    if (((byte)local_30[0] & 1) != 0) {
      operator_delete(local_20);
    }
    uVar1 = 1;
  }
  return uVar1;
}


// 002afdf0  ATCTxon::FlightFollowingCancelled

/* ATCTxon::FlightFollowingCancelled(unsigned short, std::function<void (ATCAircraft*, bool)>) */

void __thiscall ATCTxon::FlightFollowingCancelled(ATCTxon *this,uint param_2,function *param_3)

{
  undefined8 uVar1;
  
  uVar1 = 0x20;
  if (*(uint *)(this + 0xf4) == param_2) {
    uVar1 = 0x4e;
  }
  r_printf((char *)this,".flightFollowingCancelled(%c%d)",uVar1,(ulong)param_2);
  if (*(long *)(this + 0x100) != 0) {
    std::
    vector<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>,std::allocator<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>>>
    ::emplace_back<char_const(&)[25],std::function<void(ATCAircraft*,bool)>&>
              ((vector<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>,std::allocator<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>>>
                *)(*(long *)(this + 0x100) + 0x18),"FlightFollowingCancelled",param_3);
    return;
  }
  return;
}


// 002b1720  ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_40::operator()

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment const*,
   ATCTxon&)::$_40::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft const*, AIRNAV5::MagHeading) const */

undefined4 __thiscall
ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_40::operator()
          (__40 *this,ATCAircraft *param_1,float param_3)

{
  float fVar1;
  int iVar2;
  char extraout_DL;
  int iVar3;
  undefined1 auVar4 [16];
  undefined1 auVar5 [16];
  undefined1 auVar6 [16];
  GeoPoint2D local_40 [16];
  undefined8 local_30;
  undefined4 local_28 [2];
  
  (**(code **)(*(long *)param_1 + 0x70))(param_1);
  if (extraout_DL != '\0') {
    fVar1 = (float)(**(code **)(*(long *)param_1 + 0x70))(param_1);
    auVar4._0_8_ = (double)(param_3 * _DAT_0253bc00);
    auVar4._8_8_ = (double)(fVar1 * _UNK_0253bc04);
    auVar4 = divpd(auVar4,_DAT_02536f00);
    auVar5._0_4_ = (float)(int)auVar4._0_8_;
    auVar5._4_4_ = (float)(int)auVar4._8_8_;
    auVar5._8_8_ = 0;
    auVar4 = divps(auVar5,_DAT_0253bc10);
    auVar6._4_4_ = -(uint)(auVar4._4_4_ < 0.0);
    auVar6._0_4_ = -(uint)(auVar4._0_4_ < 0.0);
    auVar6._8_4_ = -(uint)(auVar4._8_4_ < 0.0);
    auVar6._12_4_ = -(uint)(auVar4._12_4_ < 0.0);
    auVar6 = blendvps(_DAT_0253ac80,_DAT_0253bc20,auVar6);
    iVar3 = (int)((float)(int)(auVar6._0_4_ + auVar4._0_4_) * (float)DAT_0253bc10);
    if (iVar3 == (int)((float)(int)(auVar6._4_4_ + auVar4._4_4_) * DAT_0253bc10._4_4_)) {
      local_28[0] = ATCAircraft::GetTrueHeading(param_1);
      local_40 = (GeoPoint2D  [16])(**(code **)(*(long *)param_1 + 0x268))(param_1);
      local_30 = GeoPoint2D::GetMagVar(local_40);
      fVar1 = (float)AIRNAV5::operator+((Angle *)local_28,(MagneticVariation *)&local_30);
      fVar1 = (float)(int)((double)(fVar1 * DAT_025201e4) / DAT_02520238) / DAT_025246d4;
      iVar2 = (int)((float)(int)(fVar1 + *(float *)(&DAT_02525220 + (ulong)(fVar1 < 0.0) * 4)) *
                   DAT_025246d4);
      if (iVar3 == iVar2) {
        return CONCAT31((int3)((uint)iVar2 >> 8),*(long *)this != 0);
      }
    }
  }
  return 0;
}


// 002bbba0  ATCTxon::AcknowledgeFlightFollowing

/* ATCTxon::AcknowledgeFlightFollowing(unsigned short, int, pressure_units_t, std::function<void
   (ATCAircraft*, bool)>) */

void __thiscall
ATCTxon::AcknowledgeFlightFollowing
          (ATCTxon *this,uint param_2_00,uint param_2,uint param_4,char *param_5)

{
  ulong uVar1;
  undefined4 *puVar2;
  allocator *paVar3;
  undefined8 *puVar4;
  byte bVar5;
  long lVar6;
  void *pvVar7;
  undefined4 uVar8;
  undefined4 uVar9;
  undefined4 uVar10;
  long lVar11;
  void *pvVar12;
  function *pfVar13;
  undefined8 uVar14;
  long lVar15;
  long *plVar16;
  void *pvVar17;
  ulong uVar18;
  void *pvVar19;
  allocator *paVar20;
  
  pfVar13 = (function *)(ulong)param_2_00;
  uVar14 = 0x20;
  if (*(uint *)(this + 0xf4) == param_2_00) {
    uVar14 = 0x4e;
  }
  r_printf((char *)this,".ackVfrFlightFollowing(%c%d|%d|%d)",uVar14,pfVar13,(ulong)param_2,
           (ulong)param_4);
  lVar6 = *(long *)(this + 0x100);
  if (lVar6 != 0) {
    paVar20 = *(allocator **)(lVar6 + 0x20);
    if (paVar20 < *(allocator **)(lVar6 + 0x28)) {
      std::
      allocator_traits<std::allocator<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>>>
      ::
      construct<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>,char_const(&)[27],std::function<void(ATCAircraft*,bool)>&,void,void>
                (paVar20,"AcknowledgeFlightFollowing",param_5,pfVar13);
      *(allocator **)(lVar6 + 0x20) = paVar20 + 0x50;
    }
    else {
      plVar16 = (long *)(lVar6 + 0x18);
      lVar15 = (long)paVar20 - *plVar16 >> 4;
      uVar1 = lVar15 * -0x3333333333333333 + 1;
      if (0x333333333333333 < uVar1) {
        std::
        __vector_base<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>,std::allocator<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>>>
        ::__throw_length_error();
LAB_002bbe64:
                    /* WARNING: Subroutine does not return */
        std::__throw_length_error((char *)plVar16);
      }
      lVar11 = (long)*(allocator **)(lVar6 + 0x28) - *plVar16 >> 4;
      uVar18 = lVar11 * -0x6666666666666666;
      if (uVar18 < uVar1) {
        uVar18 = uVar1;
      }
      pfVar13 = (function *)0x199999999999999;
      if (0x199999999999998 < (ulong)(lVar11 * -0x3333333333333333)) {
        uVar18 = 0x333333333333333;
      }
      if (uVar18 == 0) {
        pvVar12 = (void *)0x0;
      }
      else {
        if (0x333333333333333 < uVar18) goto LAB_002bbe64;
        pvVar12 = operator_new(uVar18 * 0x50);
      }
      paVar20 = (allocator *)(lVar15 * 0x10 + (long)pvVar12);
      std::
      allocator_traits<std::allocator<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>>>
      ::
      construct<std::pair<std::string,std::function<void(ATCAircraft*,bool)>>,char_const(&)[27],std::function<void(ATCAircraft*,bool)>&,void,void>
                (paVar20,"AcknowledgeFlightFollowing",param_5,pfVar13);
      pvVar12 = (void *)((long)pvVar12 + uVar18 * 0x50);
      pvVar7 = *(void **)(lVar6 + 0x18);
      pvVar19 = *(void **)(lVar6 + 0x20);
      if (pvVar19 == pvVar7) {
        *(allocator **)(lVar6 + 0x18) = paVar20;
        *(allocator **)(lVar6 + 0x20) = paVar20 + 0x50;
        *(void **)(lVar6 + 0x28) = pvVar12;
      }
      else {
        lVar15 = 0;
        pvVar17 = pvVar19;
        do {
          *(undefined8 *)(paVar20 + lVar15 + -0x40) =
               *(undefined8 *)((long)pvVar19 + lVar15 + -0x40);
          puVar2 = (undefined4 *)((long)pvVar19 + lVar15 + -0x50);
          uVar8 = puVar2[1];
          uVar9 = puVar2[2];
          uVar10 = puVar2[3];
          paVar3 = paVar20 + lVar15 + -0x50;
          *(undefined4 *)paVar3 = *puVar2;
          *(undefined4 *)(paVar3 + 4) = uVar8;
          *(undefined4 *)(paVar3 + 8) = uVar9;
          *(undefined4 *)(paVar3 + 0xc) = uVar10;
          puVar4 = (undefined8 *)((long)pvVar19 + lVar15 + -0x50);
          *puVar4 = 0;
          puVar4[1] = 0;
          *(undefined8 *)((long)pvVar19 + lVar15 + -0x40) = 0;
          lVar11 = *(long *)((long)pvVar19 + lVar15 + -0x10);
          if (lVar11 == 0) {
            *(undefined8 *)(paVar20 + lVar15 + -0x10) = 0;
          }
          else if ((long)pvVar19 + lVar15 + -0x30 == lVar11) {
            *(allocator **)(paVar20 + lVar15 + -0x10) = paVar20 + lVar15 + -0x30;
            (**(code **)(**(long **)((long)pvVar19 + lVar15 + -0x10) + 0x18))();
          }
          else {
            *(long *)(paVar20 + lVar15 + -0x10) = lVar11;
            *(undefined8 *)((long)pvVar17 + -0x10) = 0;
          }
          pvVar17 = (void *)((long)pvVar17 + -0x50);
          lVar11 = lVar15 + -0x50;
          lVar15 = lVar15 + -0x50;
        } while ((void *)((long)pvVar19 + lVar11) != pvVar7);
        pvVar7 = *(void **)(lVar6 + 0x18);
        pvVar19 = *(void **)(lVar6 + 0x20);
        *(allocator **)(lVar6 + 0x18) = paVar20 + lVar15;
        *(allocator **)(lVar6 + 0x20) = paVar20 + 0x50;
        *(void **)(lVar6 + 0x28) = pvVar12;
        for (; pvVar19 != pvVar7; pvVar19 = (void *)((long)pvVar19 + -0x50)) {
          plVar16 = *(long **)((long)pvVar19 + -0x10);
          if ((long *)((long)pvVar19 + -0x30) == plVar16) {
            (**(code **)(*plVar16 + 0x20))();
            bVar5 = *(byte *)((long)pvVar19 + -0x50);
          }
          else {
            if (plVar16 != (long *)0x0) {
              (**(code **)(*plVar16 + 0x28))();
            }
            bVar5 = *(byte *)((long)pvVar19 + -0x50);
          }
          if ((bVar5 & 1) != 0) {
            operator_delete(*(void **)((long)pvVar19 + -0x40));
          }
        }
      }
      if (pvVar7 != (void *)0x0) {
        operator_delete(pvVar7);
        return;
      }
    }
  }
  return;
}


// 002fa150  ATCRequestFileFlightPlanNotification

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* ATCRequestFileFlightPlanNotification(UTL_postcard const&) */

void ATCRequestFileFlightPlanNotification(UTL_postcard *param_1)

{
  long *plVar1;
  
  plVar1 = operator_new(0x70);
  *plVar1 = 0;
  UTL_postcard::UTL_postcard((UTL_postcard *)(plVar1 + 2),param_1);
  plVar1[1] = (long)&_s_file_flight_plan_postcards;
  *plVar1 = (long)_s_file_flight_plan_postcards;
  *(long **)((long)_s_file_flight_plan_postcards + 8) = plVar1;
  _s_file_flight_plan_postcards = plVar1;
  _DAT_0315ec38 = _DAT_0315ec38 + 1;
  return;
}


// 00303c20  ATCSetFlightInfo

/* ATCSetFlightInfo(ATCAircraft*, ATCAircraftFlightInfo const&) */

undefined8 ATCSetFlightInfo(ATCAircraft *param_1,ATCAircraftFlightInfo *param_2)

{
  if (param_1 == (ATCAircraft *)0x0) {
    param_1 = _gUsersAircraft;
  }
  std::string::operator=((string *)(param_1 + 0x200),(string *)param_2);
  std::string::operator=((string *)(param_1 + 0x218),(string *)(param_2 + 0x18));
  std::string::operator=((string *)(param_1 + 0x230),(string *)(param_2 + 0x30));
  *(undefined4 *)(param_1 + 0x248) = *(undefined4 *)(param_2 + 0x48);
  std::string::operator=((string *)(param_1 + 0x250),(string *)(param_2 + 0x50));
  return 1;
}


// 00303c90  ATCFileFlightPlan

/* ATCFileFlightPlan(ATCAircraft*, GeoPoint2D, ATCAircraftFlightPlan const&, std::string&) */

ATCFlightRoute *
ATCFileFlightPlan(undefined8 param_1_00,undefined8 param_2,ATCFlightRoute *param_1,
                 ATCAircraft *param_4,ATCAircraftFlightPlan *param_5,string *param_6)

{
  void *pvVar1;
  char *pcVar2;
  char cVar3;
  string sVar4;
  __darwin_ct_rune_t _Var5;
  ulong uVar6;
  long lVar7;
  undefined8 uVar8;
  undefined4 *puVar9;
  preferences_provider *this;
  long *plVar10;
  void *pvVar11;
  ulong uVar12;
  long *plVar13;
  long *plVar14;
  ATCAircraft *pAVar15;
  ATCAircraft *pAVar16;
  string *psVar17;
  undefined4 uVar18;
  undefined7 *puVar19;
  void *pvVar20;
  ATCAircraft AVar21;
  string *psVar22;
  ATCFlightRoute *this_00;
  string *psVar23;
  undefined8 in_stack_fffffffffffffc90;
  undefined8 in_stack_fffffffffffffc98;
  undefined4 uVar24;
  float local_358;
  float local_354;
  undefined8 local_350;
  undefined8 local_348;
  string *local_340;
  long local_338;
  long *plStack_330;
  ATCAircraft *local_320;
  ATCFlightRoute *local_318;
  string *local_310;
  byte local_308;
  char local_307 [15];
  char *local_2f8;
  byte local_2f0;
  undefined4 local_2ef;
  undefined2 local_2eb;
  undefined1 local_2e9;
  undefined4 *local_2e0;
  long local_2d8;
  long *local_2d0;
  long local_2c8;
  long *plStack_2c0;
  undefined8 local_2b8;
  undefined4 uStack_2b0;
  undefined4 uStack_2ac;
  char local_2a8;
  undefined2 uStack_2a7;
  undefined5 uStack_2a5;
  string *local_2a0;
  ATCAircraft *local_298;
  wxr_envelope_class local_290;
  undefined7 uStack_28f;
  string *local_288;
  undefined7 *local_280;
  char local_270;
  long local_38;
  
  uVar24 = (undefined4)((ulong)in_stack_fffffffffffffc98 >> 0x20);
  uVar18 = (undefined4)((ulong)in_stack_fffffffffffffc90 >> 0x20);
  local_38 = *(long *)PTR____stack_chk_guard_02ac0540;
  if (param_4 == (ATCAircraft *)0x0) {
    param_4 = _gUsersAircraft;
  }
  local_350 = param_2;
  local_348 = param_1_00;
  local_318 = param_1;
  if (((byte)*param_6 & 1) == 0) {
    *(undefined2 *)param_6 = 0;
    if (param_4[0x1b8] != (ATCAircraft)0x0) goto LAB_00303da7;
LAB_00303d01:
    ATCAircraftFlightPlan::ATCAircraftFlightPlan((ATCAircraftFlightPlan *)(param_4 + 0x110),param_5)
    ;
    param_4[0x1b8] = (ATCAircraft)0x1;
    *(undefined4 *)(param_4 + 0x1b0) = 0;
    AVar21 = param_4[0x160];
    if (((byte)AVar21 & 1) == 0) goto LAB_00303e6a;
LAB_00303d32:
    if (*(long *)(param_4 + 0x168) == 0) goto LAB_00303e85;
LAB_00303d52:
    std::operator+((char *)&local_2f0,(string *)"via ");
    AVar21 = param_4[0x118];
    if (((byte)AVar21 & 1) != 0) goto LAB_00303eba;
LAB_00303d79:
    uVar6 = (ulong)((byte)AVar21 >> 1);
  }
  else {
    **(undefined1 **)(param_6 + 0x10) = 0;
    *(undefined8 *)(param_6 + 8) = 0;
    if (param_4[0x1b8] == (ATCAircraft)0x0) goto LAB_00303d01;
LAB_00303da7:
    *(long *)(param_4 + 0x110) = *(long *)param_5;
    std::string::operator=((string *)(param_4 + 0x118),(string *)(param_5 + 8));
    std::string::operator=((string *)(param_4 + 0x130),(string *)(param_5 + 0x20));
    std::string::operator=((string *)(param_4 + 0x148),(string *)(param_5 + 0x38));
    std::string::operator=((string *)(param_4 + 0x160),(string *)(param_5 + 0x50));
    *(undefined4 *)(param_4 + 0x178) = *(undefined4 *)(param_5 + 0x68);
    *(ATCAircraftFlightPlan *)(param_4 + 0x17c) = param_5[0x6c];
    std::string::operator=((string *)(param_4 + 0x180),(string *)(param_5 + 0x70));
    std::string::operator=((string *)(param_4 + 0x198),(string *)(param_5 + 0x88));
    *(undefined4 *)(param_4 + 0x1b0) = *(undefined4 *)(param_5 + 0xa0);
    *(ATCAircraftFlightPlan *)(param_4 + 0x1b4) = param_5[0xa4];
    *(undefined4 *)(param_4 + 0x1b0) = 0;
    AVar21 = param_4[0x160];
    if (((byte)AVar21 & 1) != 0) goto LAB_00303d32;
LAB_00303e6a:
    if ((byte)AVar21 >> 1 != 0) goto LAB_00303d52;
LAB_00303e85:
    local_2f0 = 0xc;
    local_2ef = 0x65726964;
    local_2eb = 0x7463;
    local_2e9 = 0;
    AVar21 = param_4[0x118];
    if (((byte)AVar21 & 1) == 0) goto LAB_00303d79;
LAB_00303eba:
    uVar6 = *(ulong *)(param_4 + 0x120);
  }
  psVar22 = (string *)(param_4 + 0x160);
  local_320 = param_4 + 0x110;
  psVar17 = (string *)(param_4 + 0x118);
  local_340 = psVar17;
  local_310 = param_6;
  local_298 = param_4;
  if (uVar6 == 0) {
    (**(code **)(*(long *)param_4 + 0x3f8))(&local_290,param_4);
    if (((byte)local_290 & 1) == 0) {
      puVar19 = &uStack_28f;
      if (((byte)param_4[0x130] & 1) != 0) goto LAB_00303fcd;
LAB_00304264:
      pAVar16 = param_4 + 0x131;
      AVar21 = param_4[0x17c];
      if (AVar21 != (ATCAircraft)0x0) goto LAB_00303fe6;
LAB_00304281:
      pcVar2 = "No Alt Requested";
    }
    else {
      puVar19 = local_280;
      if (((byte)param_4[0x130] & 1) == 0) goto LAB_00304264;
LAB_00303fcd:
      pAVar16 = *(ATCAircraft **)(param_4 + 0x140);
      AVar21 = param_4[0x17c];
      if (AVar21 == (ATCAircraft)0x0) goto LAB_00304281;
LAB_00303fe6:
      stl_printf((char *)&local_308,"%d",(ulong)(uint)(int)*(float *)(param_4 + 0x178));
      pcVar2 = local_2f8;
      if ((local_308 & 1) == 0) {
        pcVar2 = local_307;
      }
    }
    puVar9 = local_2e0;
    if ((local_2f0 & 1) == 0) {
      puVar9 = &local_2ef;
    }
    _source_sim_log_write(1,"ATC","%s Popup FP filed to %s at %s %s, type=%d",puVar19,pAVar16,pcVar2,
                      puVar9,CONCAT44(uVar18,*(undefined4 *)local_320));
    psVar17 = local_310;
    this_00 = local_318;
    if ((AVar21 != (ATCAircraft)0x0) && ((local_308 & 1) != 0)) {
      operator_delete(local_2f8);
    }
    pAVar16 = param_4;
    if (((byte)local_290 & 1) != 0) {
      operator_delete(local_280);
    }
  }
  else {
    (**(code **)(*(long *)param_4 + 0x3f8))(&local_290,param_4);
    if (((byte)local_290 & 1) == 0) {
      puVar19 = &uStack_28f;
      if (((byte)*psVar17 & 1) != 0) goto LAB_00303f20;
LAB_0030403b:
      pAVar16 = param_4 + 0x119;
      if (((byte)param_4[0x130] & 1) != 0) goto LAB_00303f37;
LAB_0030404e:
      pAVar15 = param_4 + 0x131;
      AVar21 = param_4[0x17c];
      if (AVar21 != (ATCAircraft)0x0) goto LAB_00303f53;
LAB_0030406e:
      pcVar2 = "No Alt Requested";
    }
    else {
      puVar19 = local_280;
      if (((byte)*psVar17 & 1) == 0) goto LAB_0030403b;
LAB_00303f20:
      pAVar16 = *(ATCAircraft **)(param_4 + 0x128);
      if (((byte)param_4[0x130] & 1) == 0) goto LAB_0030404e;
LAB_00303f37:
      pAVar15 = *(ATCAircraft **)(param_4 + 0x140);
      AVar21 = param_4[0x17c];
      if (AVar21 == (ATCAircraft)0x0) goto LAB_0030406e;
LAB_00303f53:
      stl_printf((char *)&local_308,"%d",(ulong)(uint)(int)*(float *)(param_4 + 0x178));
      pcVar2 = local_2f8;
      if ((local_308 & 1) == 0) {
        pcVar2 = local_307;
      }
    }
    puVar9 = local_2e0;
    if ((local_2f0 & 1) == 0) {
      puVar9 = &local_2ef;
    }
    _source_sim_log_write(1,"ATC","%s FP filed - %s to %s at %s %s, type=%d",puVar19,pAVar16,pAVar15,
                      pcVar2,puVar9,CONCAT44(uVar24,*(undefined4 *)local_320));
    pAVar16 = local_298;
    psVar17 = local_310;
    this_00 = local_318;
    if ((AVar21 != (ATCAircraft)0x0) && ((local_308 & 1) != 0)) {
      operator_delete(local_2f8);
    }
    if (((byte)local_290 & 1) != 0) {
      operator_delete(local_280);
    }
    if (pAVar16[0x1b4] != (ATCAircraft)0x0) {
      _source_sim_log_write(1,"ATC",
                        "  Plan states NO ability to fly procedures, SID/STAR names will not be used"
                       );
    }
    ___bzero(&local_290,600);
    wxr_envelope_class::env_set_to_CAVOK(&local_290);
    psVar23 = local_340;
    local_2b8._0_4_ = 0;
    local_2b8._4_4_ = 0;
    ATCUtilsGetWxrNearApt(local_340,&local_290);
    ATCUtilsGetAptByAptID(psVar23,(vec_apt_struct **)&local_2b8);
    if (CONCAT44(local_2b8._4_4_,(uint)local_2b8) != 0) {
      wxr_envelope_class::get_alt_winds
                (&local_290,*(float *)(CONCAT44(local_2b8._4_4_,(uint)local_2b8) + 0x48),
                 (float *)&local_2d8,(float *)&local_2c8,(float *)&local_338,&local_358,&local_354);
      if (((byte)*psVar23 & 1) == 0) {
        psVar23 = psVar23 + 1;
      }
      else {
        psVar23 = *(string **)(pAVar16 + 0x128);
      }
      _source_sim_log_write(1,"ATC","Wind at %s %d %dkts",psVar23,(int)(float)local_2c8,
                        (int)(float)local_2d8);
    }
    lVar7 = (**(code **)(*(long *)pAVar16 + 0x318))(pAVar16);
    if (lVar7 != 0) {
      uVar8 = apt_get_string(*(uint *)(lVar7 + 0x1c));
      _source_sim_log_write(1,"ATC","Parked in \'%s\'",uVar8);
    }
  }
  cVar3 = ATCValidateRouteCursory(psVar22,psVar17);
  if (cVar3 == '\0') {
    *this_00 = (ATCFlightRoute)0x0;
    this_00[0x20] = (ATCFlightRoute)0x0;
    psVar17 = (string *)0x0;
    local_288 = (string *)0x0;
    goto joined_r0x00304393;
  }
  sVar4 = *psVar22;
  if (((byte)sVar4 & 1) == 0) {
    psVar17 = (string *)(param_4 + 0x161);
    psVar23 = psVar22 + (ulong)((byte)sVar4 >> 1) + 1;
    if (psVar17 == psVar23) goto LAB_003043b6;
LAB_00304350:
    do {
      _Var5 = ___toupper((int)(char)*psVar17);
      *psVar17 = SUB41(_Var5,0);
      psVar17 = psVar17 + 1;
    } while (psVar17 != psVar23);
    sVar4 = *psVar22;
    if (((byte)sVar4 & 1) == 0) goto LAB_003043ba;
LAB_0030436a:
    uVar6 = *(ulong *)(pAVar16 + 0x168);
    param_4 = *(ATCAircraft **)(pAVar16 + 0x170);
  }
  else {
    psVar17 = *(string **)(pAVar16 + 0x170);
    psVar23 = psVar17 + *(long *)(pAVar16 + 0x168);
    if (psVar17 != psVar23) goto LAB_00304350;
LAB_003043b6:
    if (((byte)sVar4 & 1) != 0) goto LAB_0030436a;
LAB_003043ba:
    param_4 = param_4 + 0x161;
    uVar6 = (ulong)((byte)sVar4 >> 1);
  }
  str_tokenize(&local_290,param_4,uVar6," _",2);
  local_2a0 = (string *)CONCAT71(uStack_28f,local_290);
  if (((byte)*psVar22 & 1) == 0) {
    *(undefined2 *)psVar22 = 0;
  }
  else {
    **(undefined1 **)(local_298 + 0x170) = 0;
    *(long *)(local_298 + 0x168) = 0;
  }
  if ((long)local_288 - (long)local_2a0 != 0) {
    uVar12 = ((long)local_288 - (long)local_2a0 >> 3) * -0x5555555555555555;
    uVar6 = 1;
    if (1 < uVar12) {
      uVar6 = uVar12;
    }
    uVar12 = 0;
    do {
      if (uVar12 == 0) {
        std::string::operator=(psVar22,local_2a0);
      }
      else {
        std::operator+((char *)&local_290,(string *)" ");
        puVar19 = local_280;
        if (((byte)local_290 & 1) == 0) {
          puVar19 = &uStack_28f;
        }
        std::string::append((char *)psVar22,(ulong)puVar19);
        if (((byte)local_290 & 1) != 0) {
          operator_delete(local_280);
        }
      }
      uVar12 = uVar12 + 1;
    } while (uVar6 != uVar12);
  }
  pAVar15 = local_298;
  ATCFlightRoute::ATCFlightRoute((ATCFlightRoute *)&local_290,local_298);
  psVar17 = local_2a0;
  pAVar16 = local_320;
  local_270 = '\x01';
  cVar3 = ATCAircraft::FileIFRFlightplan
                    ((int)local_348,local_350,pAVar15,local_320,local_310,&local_290);
  this_00 = local_318;
  if (cVar3 == '\0') {
    *local_318 = (ATCFlightRoute)0x0;
    local_318[0x20] = (ATCFlightRoute)0x0;
  }
  else {
    ATCFlightRoute::PrintRoutingLog((ATCFlightRoute *)&local_290,true);
    if (((local_298 == _gUsersAircraft) &&
        (cVar3 = (**(code **)(*(long *)local_298 + 0x1a0))(), cVar3 != '\0')) &&
       (*(int *)(local_298 + 0x6c) == 0)) {
      ATCControllerDb::FindEffectiveControllerForFacility(&local_2d8);
      if (local_2d8 == 0) {
        pAVar15 = local_298;
        (**(code **)(*(long *)local_298 + 600))(&local_2b8);
        ATCControllerDb::FindControllerForGeoPt
                  ((GeoPoint3D *)&local_2c8,SUB81(pAVar15,0),SUB81(&local_2b8,0));
        plVar14 = plStack_2c0;
        local_2d8 = local_2c8;
        plVar10 = local_2d0;
        local_2c8 = 0;
        plStack_2c0 = (long *)0x0;
        local_2d0 = plVar14;
        if (plVar10 != (long *)0x0) {
          LOCK();
          plVar14 = plVar10 + 1;
          lVar7 = *plVar14;
          *plVar14 = *plVar14 + -1;
          UNLOCK();
          if (lVar7 == 0) {
            (**(code **)(*plVar10 + 0x10))(plVar10);
            std::__shared_weak_count::__release_weak();
          }
        }
        if (plStack_2c0 != (long *)0x0) {
          LOCK();
          plVar10 = plStack_2c0 + 1;
          lVar7 = *plVar10;
          *plVar10 = *plVar10 + -1;
          UNLOCK();
          if (lVar7 == 0) {
            (**(code **)(*plStack_2c0 + 0x10))(plStack_2c0);
            std::__shared_weak_count::__release_weak();
          }
        }
        if (local_2d8 != 0) goto LAB_0030467e;
      }
      else {
LAB_0030467e:
        lVar7 = local_2d8;
        (**(code **)(*(long *)local_298 + 0x388))(local_298,1);
        (**(code **)(*(long *)local_298 + 600))(&local_2b8);
        ATCControllerDb::FindNearestControllerForChan((ATCControllerDb *)&local_2c8);
        if ((lVar7 != local_2c8) && (_g_disable_autotune == '\0')) {
          this = (preferences_provider *)misc_prefs();
          local_2b8._0_4_ = CONCAT31((int3)s_auto_tune_for_atc_027d1c97._0_8_,0x22);
          local_2b8._4_4_ = SUB84(s_auto_tune_for_atc_027d1c97._0_8_,3);
          uStack_2b0._0_1_ = SUB81(s_auto_tune_for_atc_027d1c97._0_8_,7);
          uStack_2b0._1_3_ = (undefined3)s_auto_tune_for_atc_027d1c97._8_8_;
          uStack_2ac = SUB84(s_auto_tune_for_atc_027d1c97._8_8_,3);
          local_2a8 = SUB81(s_auto_tune_for_atc_027d1c97._8_8_,7);
          uStack_2a7 = 99;
          cVar3 = preferences_provider::get_bool(this,(string *)&local_2b8,false);
          if (((uint)local_2b8 & 1) != 0) {
            operator_delete((void *)CONCAT53(uStack_2a5,CONCAT21(uStack_2a7,local_2a8)));
          }
          if (cVar3 != '\0') {
            plVar10 = *(long **)(lVar7 + 0xb0);
            uVar18 = 0xffffffff;
            if (plVar10 != (long *)0x0) {
              plVar13 = (long *)(lVar7 + 0xb0);
              plVar14 = plVar10;
              do {
                if ((ATCAircraft *)plVar14[4] >= local_298) {
                  plVar13 = plVar14;
                }
                plVar14 = (long *)plVar14[(ATCAircraft *)plVar14[4] < local_298];
              } while (plVar14 != (long *)0x0);
              if ((plVar13 != (long *)(lVar7 + 0xb0)) && ((ATCAircraft *)plVar13[4] <= local_298)) {
                do {
                  while (local_298 < (ATCAircraft *)plVar10[4]) {
                    plVar10 = (long *)*plVar10;
                    if (plVar10 == (long *)0x0) goto LAB_003047d2;
                  }
                  if (local_298 <= (ATCAircraft *)plVar10[4]) {
                    if (plVar10 != (long *)0x0) {
                      uVar18 = (undefined4)plVar10[5];
                      goto LAB_003047e8;
                    }
                    break;
                  }
                  plVar10 = (long *)plVar10[1];
                } while (plVar10 != (long *)0x0);
LAB_003047d2:
                    /* WARNING: Subroutine does not return */
                std::__throw_out_of_range("map::at:  key not found");
              }
            }
LAB_003047e8:
            (**(code **)(*(long *)local_298 + 0x360))
                      (local_298,uVar18,"Auto-tune for on-runway clearance request");
            (**(code **)(*(long *)local_298 + 0x388))(local_298,1);
            (**(code **)(*(long *)local_298 + 600))(&local_2b8);
            ATCControllerDb::FindNearestControllerForChan((ATCControllerDb *)&local_338);
            plVar10 = plStack_2c0;
            plStack_2c0 = plStack_330;
            local_2c8 = local_338;
            local_338 = 0;
            plStack_330 = (long *)0x0;
            if (plVar10 != (long *)0x0) {
              LOCK();
              plVar14 = plVar10 + 1;
              lVar7 = *plVar14;
              *plVar14 = *plVar14 + -1;
              UNLOCK();
              if (lVar7 == 0) {
                (**(code **)(*plVar10 + 0x10))(plVar10);
                std::__shared_weak_count::__release_weak();
              }
            }
            if (plStack_330 != (long *)0x0) {
              LOCK();
              plVar10 = plStack_330 + 1;
              lVar7 = *plVar10;
              *plVar10 = *plVar10 + -1;
              UNLOCK();
              if (lVar7 == 0) {
                (**(code **)(*plStack_330 + 0x10))(plStack_330);
                std::__shared_weak_count::__release_weak();
              }
            }
          }
        }
        local_2b8._0_4_ = 0;
        local_2b8._4_4_ = 0;
        uStack_2b0 = 0;
        uStack_2ac = 0;
        local_2a8 = 0;
        uStack_2a7 = 0;
        uStack_2a5 = 0;
        ATCAircraft::PilotCmdRequestIFRClearance((vector *)local_298);
        uVar24 = local_2b8._4_4_;
        uVar18 = (uint)local_2b8;
        pvVar20 = (void *)CONCAT44(local_2b8._4_4_,(uint)local_2b8);
        if (pvVar20 != (void *)0x0) {
          pvVar11 = (void *)CONCAT44(uStack_2ac,uStack_2b0);
          if ((void *)CONCAT44(uStack_2ac,uStack_2b0) != pvVar20) {
            do {
              pvVar1 = (void *)((long)pvVar11 + -0x28);
              if ((*(byte *)((long)pvVar11 + -0x20) & 1) != 0) {
                operator_delete(*(void **)((long)pvVar11 + -0x10));
              }
              pvVar11 = pvVar1;
            } while (pvVar1 != pvVar20);
            pvVar20 = (void *)CONCAT44(local_2b8._4_4_,(uint)local_2b8);
          }
          uStack_2b0 = uVar18;
          uStack_2ac = uVar24;
          operator_delete(pvVar20);
        }
        if (plStack_2c0 != (long *)0x0) {
          LOCK();
          plVar10 = plStack_2c0 + 1;
          lVar7 = *plVar10;
          *plVar10 = *plVar10 + -1;
          UNLOCK();
          if (lVar7 == 0) {
            (**(code **)(*plStack_2c0 + 0x10))(plStack_2c0);
            std::__shared_weak_count::__release_weak();
          }
        }
      }
      psVar17 = local_2a0;
      if (local_2d0 != (long *)0x0) {
        LOCK();
        plVar10 = local_2d0 + 1;
        lVar7 = *plVar10;
        *plVar10 = *plVar10 + -1;
        UNLOCK();
        if (lVar7 == 0) {
          (**(code **)(*local_2d0 + 0x10))(local_2d0);
          std::__shared_weak_count::__release_weak();
        }
      }
    }
    if ((*(int *)(local_298 + 0x114) != 1) ||
       ((local_298 == _gUsersAircraft &&
        (UTL_notifiable::SendNotification(2,0x10,pAVar16), *(int *)(local_298 + 0x114) != 1)))) {
      if (local_270 != '\0') {
        ATCFlightRoute::~ATCFlightRoute((ATCFlightRoute *)&local_290);
      }
      *this_00 = (ATCFlightRoute)0x0;
      this_00[0x20] = (ATCFlightRoute)0x0;
      goto joined_r0x00304393;
    }
    *this_00 = (ATCFlightRoute)0x0;
    this_00[0x20] = (ATCFlightRoute)0x0;
    if (local_270 == '\0') goto joined_r0x00304393;
    ATCFlightRoute::ATCFlightRoute(this_00,(ATCFlightRoute *)&local_290);
    this_00[0x20] = (ATCFlightRoute)0x1;
  }
  if (local_270 != '\0') {
    ATCFlightRoute::~ATCFlightRoute((ATCFlightRoute *)&local_290);
  }
joined_r0x00304393:
  if ((local_2f0 & 1) != 0) {
    operator_delete(local_2e0);
  }
  if (psVar17 != (string *)0x0) {
    while (psVar22 = local_288, psVar22 != psVar17) {
      local_288 = psVar22 + -0x18;
      if (((byte)psVar22[-0x18] & 1) != 0) {
        operator_delete(*(void **)(psVar22 + -8));
      }
    }
    operator_delete(psVar17);
  }
  if (*(long *)PTR____stack_chk_guard_02ac0540 != local_38) {
                    /* WARNING: Subroutine does not return */
    ___stack_chk_fail();
  }
  return this_00;
}


// 0031afa0  ATCTxon::RequestFlightFollowing

/* ATCTxon::RequestFlightFollowing(ATCAircraft const*) */

void __thiscall ATCTxon::RequestFlightFollowing(ATCTxon *this,ATCAircraft *param_1)

{
  void *pvVar1;
  Airport *pAVar2;
  flt_class *pfVar3;
  long lVar4;
  long lVar5;
  NavDataBase *this_00;
  FlightRoute *this_01;
  uint uVar6;
  ulong uVar7;
  byte bVar8;
  Airport *pAVar9;
  void *pvVar10;
  float fVar11;
  undefined8 local_88;
  ulong uStack_80;
  void *local_78;
  undefined8 local_68;
  ulong uStack_60;
  void *local_58;
  float local_4c;
  undefined8 local_48;
  Airport *pAStack_40;
  void *local_38;
  
  local_68 = 0;
  uStack_60 = 0;
  local_58 = (void *)0x0;
  local_88 = 0;
  uStack_80 = 0;
  local_78 = (void *)0x0;
  if (_gP0Aircraft == param_1) {
    GetP0GarminSrcDst((string *)&local_68,(string *)&local_88);
    uVar6 = (uint)local_68 & 0xff;
  }
  else {
    uVar6 = 0;
  }
  uVar7 = (ulong)(uVar6 >> 1);
  if ((uVar6 & 1) != 0) {
    uVar7 = uStack_60;
  }
  if (uVar7 == 0) {
    if ((_stg < 0) || ((int)((ulong)(DAT_03a16b30 - _vec_apt) >> 5) * -0x33333333 + -1 < _stg)) {
      local_48 = (Airport *)0x0;
      pfVar3 = (flt_class *)
               flt_or_veh_container<flt_class>::operator[]
                         ((flt_or_veh_container<flt_class> *)&_flt,0);
      get_target_airport_and_runway_for_approach
                (pfVar3,(vec_apt_struct **)&local_48,(vec_rwy_struct **)0x0,(glideslope_ref_t *)0x0)
      ;
      if (local_48 != (Airport *)0x0) {
        std::string::assign((char *)&local_68);
      }
    }
    else {
      std::string::assign((char *)&local_68);
    }
    if (_gP0Aircraft == param_1) {
      if ((local_68 & 1) == 0) {
        if ((byte)local_68._0_1_ >> 1 == 0) goto LAB_0031b09d;
      }
      else if (uStack_60 == 0) goto LAB_0031b09d;
      local_48 = (Airport *)0x0;
      pAStack_40 = (Airport *)0x0;
      local_38 = (void *)0x0;
      lVar4 = flt_or_veh_container<veh_class>::operator[]
                        ((flt_or_veh_container<veh_class> *)&_veh,0);
      this_00 = (NavDataBase *)GarminUnits::navdata(*(GarminUnits **)(lVar4 + 0x1d18));
      AIRNAV5::Database::NavDataBase::get<AIRNAV5::Navigation::Airport>
                (this_00,(string *)&local_68,(vector *)&local_48);
      if (local_48 != pAStack_40) {
        lVar4 = flt_or_veh_container<veh_class>::operator[]
                          ((flt_or_veh_container<veh_class> *)&_veh);
        this_01 = (FlightRoute *)GarminUnits::route(*(GarminUnits **)(lVar4 + 0x1d18),0);
        AIRNAV5::Navigation::FlightRoute::setDepartureAirport(this_01,local_48,false);
      }
      pAVar2 = local_48;
      pAVar9 = pAStack_40;
      if (local_48 != (Airport *)0x0) {
        while (pAVar9 != pAVar2) {
          pAVar9 = pAVar9 + -0x228;
          (*(code *)**(undefined8 **)pAVar9)(pAVar9);
        }
        pAStack_40 = pAVar2;
        operator_delete(local_48);
      }
    }
  }
LAB_0031b09d:
  fVar11 = (float)(**(code **)(*(long *)param_1 + 0x2d8))(param_1,DAT_03c9dd93 == '\0');
  bVar8 = (byte)local_88._0_1_ & 1;
  uVar7 = uStack_80;
  if ((local_88 & 1) == 0) {
    uVar7 = (ulong)((byte)local_88._0_1_ >> 1);
  }
  pvVar1 = local_58;
  if ((local_68 & 1) == 0) {
    pvVar1 = (void *)((long)&local_68 + 1);
  }
  local_4c = ((fVar11 * DAT_02525330 * DAT_02525330) / DAT_02536f14) / DAT_02536f10;
  if (uVar7 == 0) {
    lVar4 = _lroundf();
    lVar5 = _lroundf(*(undefined4 *)(this + 0xf0));
    pAVar9 = local_48;
    local_48._0_3_ = CONCAT21((ushort)(lVar4 <= lVar5) * 0x800 + 0x4c46,4);
    local_48._4_4_ = SUB84(pAVar9,4);
    local_48._0_4_ = (uint)(uint3)local_48;
    r_printf((char *)this,".vfrFlightFollowing(%s|%s%d)",pvVar1,(long)&local_48 + 1,
             (ulong)(uint)(int)local_4c);
    if (((ulong)local_48 & 1) != 0) {
      operator_delete(local_38);
    }
  }
  else {
    pvVar10 = local_78;
    if ((local_88 & 1) == 0) {
      pvVar10 = (void *)((long)&local_88 + 1);
    }
    lVar4 = _lroundf();
    lVar5 = _lroundf(*(undefined4 *)(this + 0xf0));
    pAVar9 = local_48;
    local_48._0_3_ = CONCAT21((ushort)(lVar4 <= lVar5) * 0x800 + 0x4c46,4);
    local_48._4_4_ = SUB84(pAVar9,4);
    local_48._0_4_ = (uint)(uint3)local_48;
    r_printf((char *)this,".vfrFlightFollowing(%s|%s|%s%d)",pvVar1,pvVar10,(long)&local_48 + 1,
             (ulong)(uint)(int)local_4c);
    if (((ulong)local_48 & 1) != 0) {
      operator_delete(local_38);
    }
    bVar8 = (byte)local_88._0_1_ & 1;
  }
  if (bVar8 != 0) {
    operator_delete(local_78);
  }
  if ((local_68 & 1) != 0) {
    operator_delete(local_58);
  }
  return;
}


// 0031c100  ATCTxon::RequestCancelFlightFollowing

/* ATCTxon::RequestCancelFlightFollowing() */

void __thiscall ATCTxon::RequestCancelFlightFollowing(ATCTxon *this)

{
  r_printf((char *)this,".cancelFlightFollowing()");
  return;
}


// 0031c1e0  ATCTxon::LowPassUnavailable

/* ATCTxon::LowPassUnavailable(bool) */

void __thiscall ATCTxon::LowPassUnavailable(ATCTxon *this,bool param_1)

{
  char *pcVar1;
  undefined7 in_register_00000031;
  
  pcVar1 = "";
  if ((int)CONCAT71(in_register_00000031,param_1) != 0) {
    pcVar1 = "F14";
  }
  r_printf((char *)this,".lowPassDenied(%s)",pcVar1);
  return;
}


// 00339e60  ATCTaskCheckCourseProgress::CheckTaxiSeg(ATCFlightSegment*,float&,bool)::$_174::operator()

/* ATCTaskCheckCourseProgress::CheckTaxiSeg(ATCFlightSegment*, float&,
   bool)::$_174::TEMPNAMEPLACEHOLDERVALUE(ATCFlightSegment const*) const */

undefined8 __thiscall
ATCTaskCheckCourseProgress::CheckTaxiSeg(ATCFlightSegment*,float&,bool)::$_174::operator()
          (__174 *this,ATCFlightSegment *param_1)

{
  undefined7 uVar2;
  ATCWaypoint *this_00;
  GeoPoint2D *pGVar1;
  char cVar3;
  ulong uVar4;
  long lVar5;
  char cVar6;
  long lVar7;
  long *plVar8;
  long lVar9;
  float fVar10;
  
  if (param_1[0x84] != (ATCFlightSegment)0x0) {
    return 0;
  }
  uVar4 = *(ulong *)(this + 0x308);
  lVar5 = *(long *)(this + 0x2f0);
  lVar7 = *(long *)(this + 0x2f8);
  plVar8 = (long *)(lVar5 + (*(long *)(this + 0x310) + uVar4 >> 7) * 8);
  if (lVar7 == lVar5) {
    lVar9 = 0;
  }
  else {
    lVar9 = (ulong)((uint)(*(long *)(this + 0x310) + uVar4) & 0x7f) * 0x20 + *plVar8;
  }
  while( true ) {
    uVar2 = (undefined7)((ulong)lVar5 >> 8);
    if (lVar7 == lVar5) {
      if (lVar9 == 0) {
        return CONCAT71(uVar2,1);
      }
    }
    else if (lVar9 == (ulong)((uint)uVar4 & 0x7f) * 0x20 + *(long *)(lVar5 + (uVar4 >> 7) * 8)) {
      return CONCAT71(uVar2,1);
    }
    lVar5 = lVar9;
    if (*plVar8 == lVar9) {
      lVar5 = plVar8[-1] + 0x1000;
    }
    if ((double)*(float *)(lVar5 + -0x20) <= DAT_0315d538 + DAT_0253af20) break;
    this_00 = (ATCWaypoint *)ATCFlightSegment::GetSrcPt(param_1);
    pGVar1 = (GeoPoint2D *)ATCWaypoint::GetGeoCoords(this_00);
    lVar5 = lVar9;
    if (*plVar8 == lVar9) {
      lVar5 = plVar8[-1] + 0x1000;
    }
    fVar10 = (float)ATCGeomDistBetweenLonLatPts(pGVar1,(GeoPoint2D *)(lVar5 + -0x18));
    fVar10 = fVar10 * DAT_02536f1c;
    cVar6 = '\0';
    if (fVar10 != DAT_02525330) {
      cVar6 = -0x7f;
    }
    cVar3 = '\x01';
    if (fVar10 <= DAT_02525330) {
      cVar3 = cVar6;
    }
    if (fVar10 < DAT_02525330) {
      cVar3 = -1;
    }
    if ((cVar3 != -0x7f) && (cVar3 < '\0')) {
      return 0;
    }
    if (lVar9 == *plVar8) {
      lVar9 = plVar8[-1] + 0x1000;
      plVar8 = plVar8 + -1;
    }
    lVar9 = lVar9 + -0x20;
    lVar5 = *(long *)(this + 0x2f0);
    lVar7 = *(long *)(this + 0x2f8);
    uVar4 = *(ulong *)(this + 0x308);
  }
  return CONCAT71(uVar2,1);
}


// 0033be30  ATCTaskCheckCourseProgress::CheckRunwaySeg(ATCFlightSegment*,float&,bool)::$_179::operator()

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */
/* ATCTaskCheckCourseProgress::CheckRunwaySeg(ATCFlightSegment*, float&,
   bool)::$_179::TEMPNAMEPLACEHOLDERVALUE() const */

vec_sta_struct * __thiscall
ATCTaskCheckCourseProgress::CheckRunwaySeg(ATCFlightSegment*,float&,bool)::$_179::operator()
          (__179 *this)

{
  ATCFlightRoute *this_00;
  ATCFlightRoute *this_01;
  ATCControllerCab *this_02;
  ATCAircraft *pAVar1;
  bool bVar2;
  bool bVar3;
  __179 *p_Var4;
  char cVar5;
  int iVar6;
  undefined4 uVar7;
  long lVar8;
  ATCWaypoint *pAVar9;
  long lVar10;
  long *plVar11;
  undefined8 uVar12;
  long lVar13;
  __tree_node_base *p_Var14;
  ATCFlightSegment *this_03;
  long *plVar15;
  ATCNetwork_halfedge *pAVar16;
  char *pcVar17;
  size_t sVar18;
  undefined1 *puVar19;
  GeoPoint2D *pGVar20;
  long *plVar21;
  undefined8 uVar22;
  vec_sta_struct *pvVar23;
  ATCController *pAVar24;
  bool bVar25;
  float fVar26;
  ulong uVar27;
  float fVar28;
  undefined1 auVar29 [16];
  undefined1 local_220 [16];
  undefined1 *local_210;
  undefined8 local_d0;
  long *local_c8;
  undefined8 local_c0;
  long *local_b8;
  undefined1 *local_b0;
  long local_a8;
  undefined8 local_98;
  undefined4 local_90 [2];
  undefined8 local_88;
  long *local_80;
  undefined1 local_78 [16];
  string *local_68;
  undefined1 local_60 [16];
  undefined1 *local_50;
  long *local_48;
  vec_sta_struct *local_40;
  __179 *local_38;
  
  pAVar24 = (ATCController *)**(long **)this;
  lVar10 = **(long **)(this + 8);
  if (4 < *(int *)(pAVar24 + 0x80)) {
    uVar22 = 0xc;
    goto LAB_0033c452;
  }
  lVar13 = *(long *)(this + 0x18);
  local_38 = this;
  if (*(int *)(lVar10 + 0x268) != 0xf) {
    if ((*(int *)(lVar10 + 0x268) == 7) &&
       (lVar8 = ATCFlightRoute::GetStart(*(ATCFlightRoute **)(lVar10 + 0x60)), lVar8 != 0)) {
      pAVar9 = (ATCWaypoint *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(lVar10 + 0x60));
      lVar10 = ATCWaypoint::GetNextSeg(pAVar9);
      if (lVar10 != 0) {
        lVar10 = **(long **)(local_38 + 8);
        ATCFlightRoute::GetStart(*(ATCFlightRoute **)(lVar10 + 0x60));
        pAVar9 = (ATCWaypoint *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(lVar10 + 0x60));
        lVar10 = ATCWaypoint::GetNextSeg(pAVar9);
        if (*(int *)(lVar10 + 8) == 4) goto LAB_0033bee1;
      }
    }
    pAVar24 = (ATCController *)**(undefined8 **)local_38;
    lVar10 = **(long **)(local_38 + 8);
    uVar22 = 10;
LAB_0033c452:
    ATCController::SlapAircraft(pAVar24,lVar10,uVar22);
    return (vec_sta_struct *)0x0;
  }
LAB_0033bee1:
  local_80 = (long *)local_78;
  local_78 = (undefined1  [16])0x0;
  local_48 = (long *)(lVar13 + 0xa0);
  local_68 = (string *)(lVar13 + 0x28);
  local_b0 = local_220 + 1;
  local_a8 = lVar13;
  do {
    lVar10 = local_a8;
    local_40 = (vec_sta_struct *)(**(code **)(*(long *)**(undefined8 **)(local_38 + 8) + 0x318))();
    if (local_40 == (vec_sta_struct *)0x0) {
      iVar6 = ATCUtilsAllocateAirportGate
                        ((ATCAircraft *)**(undefined8 **)(local_38 + 8),
                         (string *)(**(long **)(local_38 + 0x10) + 0x68),&local_40,(set *)&local_80)
      ;
      if (iVar6 < 0) {
        uVar27 = **(ulong **)(local_38 + 8);
        plVar21 = (long *)*local_48;
        plVar11 = local_48;
        if (plVar21 == (long *)0x0) {
LAB_0033c006:
          p_Var14 = operator_new(0x28);
          *(ulong *)(p_Var14 + 0x20) = uVar27;
          plVar21 = local_48;
          plVar11 = (long *)*local_48;
          if ((long *)*local_48 == (long *)0x0) {
            plVar15 = local_48;
            if (*local_48 != 0) goto LAB_0033c09d;
LAB_0033c029:
            *(undefined1 (*) [16])p_Var14 = (undefined1  [16])0x0;
            *(long **)(p_Var14 + 0x10) = plVar15;
            *plVar21 = (long)p_Var14;
            if (**(long **)(lVar10 + 0x98) != 0) {
              *(long *)(lVar10 + 0x98) = **(long **)(lVar10 + 0x98);
              p_Var14 = (__tree_node_base *)*plVar21;
            }
            std::__tree_balance_after_insert<std::__tree_node_base<void*>*>
                      (*(__tree_node_base **)(lVar10 + 0xa0),p_Var14);
            *(long *)(lVar10 + 0xa8) = *(long *)(lVar10 + 0xa8) + 1;
          }
          else {
            do {
              while (plVar15 = plVar11, uVar27 < (ulong)plVar15[4]) {
                plVar21 = plVar15;
                plVar11 = (long *)*plVar15;
                if ((long *)*plVar15 == (long *)0x0) {
                  lVar13 = *plVar15;
                  goto joined_r0x0033c431;
                }
              }
              if (uVar27 <= (ulong)plVar15[4]) break;
              plVar21 = plVar15 + 1;
              plVar11 = (long *)plVar15[1];
            } while ((long *)plVar15[1] != (long *)0x0);
            lVar13 = *plVar21;
joined_r0x0033c431:
            if (lVar13 == 0) goto LAB_0033c029;
LAB_0033c09d:
            operator_delete(p_Var14);
          }
          std::string::string((string *)local_220,local_68);
          puVar19 = local_220 + 1;
          if ((local_220._0_8_ & 1) != 0) {
            puVar19 = local_210;
          }
          _source_sim_log_write(3,"ATC",
                            "Unable to assign parking %s during an initial routing to gate at %s",
                            puVar19,*(long *)(**(long **)(local_38 + 0x20) + 0x78) + 0x54);
          goto LAB_0033c11f;
        }
        do {
          if ((ulong)plVar21[4] >= uVar27) {
            plVar11 = plVar21;
          }
          plVar21 = (long *)plVar21[(ulong)plVar21[4] < uVar27];
        } while (plVar21 != (long *)0x0);
        if ((plVar11 == local_48) || (uVar27 < (ulong)plVar11[4])) goto LAB_0033c006;
      }
      else {
        std::string::string((string *)local_220,local_68);
        puVar19 = local_220 + 1;
        if ((local_220._0_8_ & 1) != 0) {
          puVar19 = local_210;
        }
        uVar22 = apt_get_string(*(uint *)(local_40 + 0x1c));
        lVar10 = **(long **)(local_38 + 0x10);
        if ((*(byte *)(lVar10 + 0x68) & 1) == 0) {
          lVar10 = lVar10 + 0x69;
        }
        else {
          lVar10 = *(long *)(lVar10 + 0x78);
        }
        _source_sim_log_write(1,"ATC","Aircraft %s assigned to arrival gate %s at %s\n",puVar19,uVar22,
                          lVar10);
LAB_0033c11f:
        if ((local_220._0_8_ & 1) != 0) {
          operator_delete(local_210);
        }
      }
      if (local_40 == (vec_sta_struct *)0x0) goto LAB_0033c4a9;
    }
    p_Var4 = local_38;
    this_00 = *(ATCFlightRoute **)(**(long **)(local_38 + 8) + 0x60);
    ATCFlightRoute::StartEdit(this_00);
    ATCRouteUtils::AppendGate(*(ATCFlightRoute **)(**(long **)(p_Var4 + 8) + 0x60),local_40);
    local_c0 = **(undefined8 **)(local_38 + 0x10);
    local_b8 = (long *)(*(undefined8 **)(local_38 + 0x10))[1];
    if (local_b8 != (long *)0x0) {
      LOCK();
      local_b8[1] = local_b8[1] + 1;
      UNLOCK();
    }
    lVar10 = **(long **)(local_38 + 8);
    uVar22 = ATCFlightRoute::GetEnd(*(ATCFlightRoute **)(lVar10 + 0x60));
    cVar5 = ATCTaxiRouteUtils::CreateTaxiRouteToGate(&local_c0,lVar10,uVar22);
    if (local_b8 != (long *)0x0) {
      LOCK();
      plVar21 = local_b8 + 1;
      lVar10 = *plVar21;
      *plVar21 = *plVar21 + -1;
      UNLOCK();
      if (lVar10 == 0) {
        (**(code **)(*local_b8 + 0x10))(local_b8);
        std::__shared_weak_count::__release_weak();
      }
    }
    if (cVar5 == '\0') {
      std::string::string((string *)local_220,local_68);
      puVar19 = local_210;
      uVar22 = local_220._0_8_;
      uVar12 = apt_get_string(*(uint *)(local_40 + 0x1c));
      if ((uVar22 & 1) == 0) {
        puVar19 = local_220 + 1;
      }
      _source_sim_log_write(3,"ATC",
                        "CreateTaxiRouteToGate failed for %s during an initial routing to gate %s at %s"
                        ,puVar19,uVar12,*(long *)(**(long **)(local_38 + 0x20) + 0x78) + 0x54);
      if ((local_220._0_8_ & 1) != 0) {
        operator_delete(local_210);
      }
      lVar10 = ATCFlightRoute::GetStart(*(ATCFlightRoute **)(**(long **)(local_38 + 8) + 0x60));
      lVar13 = ATCFlightRoute::GetEnd(*(ATCFlightRoute **)(**(long **)(local_38 + 8) + 0x60));
      this_01 = *(ATCFlightRoute **)(**(long **)(local_38 + 8) + 0x60);
      if (lVar10 == lVar13) {
        ATCFlightRoute::Clear(this_01);
      }
      else {
        pAVar9 = (ATCWaypoint *)ATCFlightRoute::GetEnd(this_01);
        pAVar9 = (ATCWaypoint *)ATCWaypoint::GetPrevPt(pAVar9);
        ATCFlightRoute::TrimAfter(this_01,pAVar9);
      }
      pvVar23 = local_40;
      plVar21 = (long *)local_78;
      plVar15 = (long *)local_78._0_8_;
      plVar11 = plVar21;
      if ((long *)local_78._0_8_ == (long *)0x0) {
LAB_0033c34a:
        p_Var14 = operator_new(0x28);
        *(vec_sta_struct **)(p_Var14 + 0x20) = pvVar23;
        *(undefined1 (*) [16])p_Var14 = (undefined1  [16])0x0;
        *(long **)(p_Var14 + 0x10) = plVar21;
        *plVar11 = (long)p_Var14;
        if ((long *)*local_80 != (long *)0x0) {
          p_Var14 = (__tree_node_base *)*plVar11;
          local_80 = (long *)*local_80;
        }
        std::__tree_balance_after_insert<std::__tree_node_base<void*>*>
                  ((__tree_node_base *)local_78._0_8_,p_Var14);
        local_78._8_8_ = local_78._8_8_ + 1;
      }
      else {
        do {
          while (plVar21 = plVar15, local_40 < (vec_sta_struct *)plVar21[4]) {
            plVar15 = (long *)*plVar21;
            plVar11 = plVar21;
            if ((long *)*plVar21 == (long *)0x0) {
              lVar10 = *plVar21;
              goto joined_r0x0033c397;
            }
          }
          if (local_40 <= (vec_sta_struct *)plVar21[4]) break;
          plVar11 = plVar21 + 1;
          plVar15 = (long *)plVar21[1];
        } while ((long *)plVar21[1] != (long *)0x0);
        lVar10 = *plVar11;
joined_r0x0033c397:
        if (lVar10 == 0) goto LAB_0033c34a;
      }
      local_40 = (vec_sta_struct *)0x0;
      uVar7 = (**(code **)(*(long *)**(undefined8 **)(local_38 + 8) + 0x408))();
      lVar10 = flt_or_veh_container<flt_class>::operator[]
                         ((flt_or_veh_container<flt_class> *)&_flt,uVar7);
      *(undefined8 *)(lVar10 + 0x6648) = 0;
      uVar7 = (**(code **)(*(long *)**(undefined8 **)(local_38 + 8) + 0x408))();
      lVar10 = flt_or_veh_container<flt_class>::operator[]
                         ((flt_or_veh_container<flt_class> *)&_flt,uVar7);
      *(undefined8 *)(lVar10 + 0x6640) = 0;
    }
    ATCFlightRoute::FinishEdit(this_00,true);
  } while ((cVar5 == '\0') && (local_40 != (vec_sta_struct *)0x0));
  if (local_40 != (vec_sta_struct *)0x0) {
    lVar10 = **(long **)(local_38 + 8);
    lVar13 = ATCFlightRoute::GetStart(*(ATCFlightRoute **)(lVar10 + 0x60));
    if (lVar13 == 0) {
      this_03 = (ATCFlightSegment *)0x0;
    }
    else {
      pAVar9 = (ATCWaypoint *)ATCFlightRoute::GetStart(*(ATCFlightRoute **)(lVar10 + 0x60));
      this_03 = (ATCFlightSegment *)ATCWaypoint::GetNextSeg(pAVar9);
    }
    while( true ) {
      if (this_03 == (ATCFlightSegment *)0x0) break;
      this_02 = (ATCControllerCab *)**(undefined8 **)(local_38 + 0x10);
      pAVar16 = (ATCNetwork_halfedge *)ATCFlightSegment::GetUnderlying(this_03);
      cVar5 = ATCControllerCab::IsActiveZone(this_02,pAVar16,(runway_spec_t *)0x0);
      if (cVar5 == '\0') {
        local_a8 = ATCFlightSegment::GetTrueCourse(this_03);
        pAVar1 = (ATCAircraft *)**(undefined8 **)(local_38 + 8);
        uVar7 = ATCAircraft::GetTrueHeading(pAVar1);
        local_88 = CONCAT44(local_88._4_4_,uVar7);
        local_220 = (**(code **)(*(long *)pAVar1 + 0x268))(pAVar1);
        local_98 = GeoPoint2D::GetMagVar((GeoPoint2D *)local_220);
        local_60._0_8_ = AIRNAV5::operator+((Angle *)&local_88,(MagneticVariation *)&local_98);
        uVar27 = (**(code **)(*(long *)pAVar1 + 0x240))(pAVar1);
        fVar26 = (float)ATCAircraft::CalcTrueCourseFromMagHeadingAndWCA
                                  (pAVar1,local_60,uVar27 & 0xffffffff | 0x100000000);
        fVar26 = ((float)local_a8 - fVar26) + DAT_02536f54;
        fVar26 = fVar26 - (float)(int)((double)fVar26 / DAT_02520250) * DAT_02520294;
        fVar26 = (float)(~-(uint)(fVar26 < 0.0) & (uint)fVar26 |
                        (uint)(fVar26 + DAT_02520294) & -(uint)(fVar26 < 0.0)) + DAT_0253acec;
        if (DAT_0253acec <= fVar26) {
          if (DAT_02536f54 < fVar26) {
            fVar26 = fVar26 + DAT_02520290;
          }
        }
        else {
          fVar26 = fVar26 + DAT_02520294;
        }
        fVar28 = (float)(~-(uint)(0.0 < fVar26) & (_DAT_02520b30 ^ (uint)fVar26) |
                        -(uint)(0.0 < fVar26) & (uint)fVar26);
        fVar28 = fVar28 - (float)(int)((double)fVar28 / DAT_02520250) * DAT_02520294;
        fVar28 = (float)(~-(uint)(fVar28 < 0.0) & (uint)fVar28 |
                        (uint)(fVar28 + DAT_02520294) & -(uint)(fVar28 < 0.0));
        fVar28 = (float)(~-(uint)(DAT_02536f54 < fVar28) & (uint)fVar28 |
                        (uint)(DAT_02520294 - fVar28) & -(uint)(DAT_02536f54 < fVar28));
        bVar2 = false;
        if (fVar28 < DAT_0253ae00) {
          bVar25 = false;
        }
        else {
          fVar28 = fVar28 + DAT_0253ae04;
          bVar25 = false;
          bVar2 = false;
          if ((double)fVar28 <= DAT_02520238) {
            bVar2 = false;
            bVar25 = false;
            if (DAT_0253acf8 <
                (float)(~-(uint)(0.0 < fVar28) & (_DAT_02520b30 ^ (uint)fVar28) |
                       (uint)fVar28 & -(uint)(0.0 < fVar28))) {
              bVar25 = DAT_02520238 < (double)fVar26 || fVar26 < 0.0;
              bVar2 = true;
            }
          }
        }
        local_60 = (**(code **)(*(long *)**(undefined8 **)(local_38 + 8) + 0x268))();
        pAVar9 = (ATCWaypoint *)ATCFlightSegment::GetSrcPt(this_03);
        pGVar20 = (GeoPoint2D *)ATCWaypoint::GetGeoCoords(pAVar9);
        local_a8 = ATCGeomHeadingBetweenLonLatPts((GeoPoint2D *)local_60,pGVar20);
        pAVar1 = (ATCAircraft *)**(undefined8 **)(local_38 + 8);
        local_90[0] = ATCAircraft::GetTrueHeading(pAVar1);
        auVar29 = (**(code **)(*(long *)pAVar1 + 0x268))(pAVar1);
        local_220 = auVar29;
        local_88 = GeoPoint2D::GetMagVar((GeoPoint2D *)local_220);
        local_98 = AIRNAV5::operator+((Angle *)local_90,(MagneticVariation *)&local_88);
        uVar27 = (**(code **)(*(long *)pAVar1 + 0x240))(pAVar1);
        fVar26 = (float)ATCAircraft::CalcTrueCourseFromMagHeadingAndWCA
                                  (pAVar1,&local_98,uVar27 & 0xffffffff | 0x100000000);
        fVar26 = (float)local_a8 - fVar26;
        fVar26 = (float)(~-(uint)(0.0 < fVar26) & (_DAT_02520b30 ^ (uint)fVar26) |
                        (uint)fVar26 & -(uint)(0.0 < fVar26));
        fVar26 = fVar26 - (float)(int)((double)fVar26 / DAT_02520250) * DAT_02520294;
        fVar26 = (float)(~-(uint)(fVar26 < 0.0) & (uint)fVar26 |
                        (uint)(fVar26 + DAT_02520294) & -(uint)(fVar26 < 0.0));
        fVar26 = (float)(~-(uint)(DAT_02536f54 < fVar26) & (uint)fVar26 |
                        (uint)(DAT_02520294 - fVar26) & -(uint)(DAT_02536f54 < fVar26));
        bVar3 = false;
        if ((fVar26 < DAT_0253be78) ||
           (fVar26 = fVar26 + _DAT_0253be7c, DAT_02520238 < (double)fVar26)) goto LAB_0033c592;
        if ((float)(~-(uint)(0.0 < fVar26) & (_DAT_02520b30 ^ (uint)fVar26) |
                   (uint)fVar26 & -(uint)(0.0 < fVar26)) <= DAT_0253acf8) goto LAB_0033c590;
        bVar25 = (bool)(bVar25 ^ 1);
        bVar3 = true;
        goto LAB_0033c592;
      }
      this_03 = (ATCFlightSegment *)ATCFlightSegment::GetNextSeg(this_03);
    }
    bVar25 = false;
    bVar2 = false;
LAB_0033c590:
    bVar3 = false;
LAB_0033c592:
    ATCController::IssueInitialTaxiClearance
              ((ATCController *)**(undefined8 **)local_38,
               (ATCAircraft *)**(undefined8 **)(local_38 + 8),false);
    pvVar23 = local_40;
    if (!bVar2) goto LAB_0033c9c6;
    local_d0 = **(undefined8 **)local_38;
    plVar21 = (long *)(*(undefined8 **)local_38)[1];
    if (plVar21 != (long *)0x0) {
      LOCK();
      plVar21[1] = plVar21[1] + 1;
      UNLOCK();
    }
    local_c8 = plVar21;
    ::ATCTxon::ATCTxon((ATCTxon *)local_220,&local_d0,**(undefined8 **)(local_38 + 8));
    if (plVar21 != (long *)0x0) {
      LOCK();
      plVar11 = plVar21 + 1;
      lVar10 = *plVar11;
      *plVar11 = *plVar11 + -1;
      UNLOCK();
      if (lVar10 == 0) {
        (**(code **)(*plVar21 + 0x10))(plVar21);
        std::__shared_weak_count::__release_weak();
      }
    }
    if (bVar3) {
      pcVar17 = (char *)runway_spec_t::to_string
                                  ((runway_spec_t *)(**(long **)(local_38 + 0x20) + 0xa0));
      sVar18 = _strlen(pcVar17);
      if (0xffffffffffffffef < sVar18) {
                    /* WARNING: Subroutine does not return */
        std::string::__throw_length_error();
      }
      if (sVar18 < 0x17) {
        local_60[0] = (char)sVar18 * '\x02';
        puVar19 = local_60 + 1;
        if (sVar18 != 0) goto LAB_0033c92a;
      }
      else {
        uVar27 = sVar18 + 0x10 & 0xfffffffffffffff0;
        puVar19 = operator_new(uVar27);
        local_60._0_8_ = uVar27 | 1;
        local_60._8_8_ = sVar18;
        local_50 = puVar19;
LAB_0033c92a:
        _memcpy(puVar19,pcVar17,sVar18);
      }
      puVar19[sVar18] = 0;
      puVar19 = local_50;
      if ((local_60._0_8_ & 1) == 0) {
        puVar19 = local_60 + 1;
      }
      ::ATCTxon::r_printf(local_220,".backtrackRwy(%s)",puVar19);
      if ((local_60._0_8_ & 1) != 0) {
        operator_delete(local_50);
      }
    }
    pcVar17 = ".vacateRunway(0)";
    if (!bVar25) {
      pcVar17 = ".vacateRunway(1)";
    }
    ::ATCTxon::r_printf(local_220,pcVar17);
    ATCController::CreateTxon
              ((ATCController *)**(undefined8 **)local_38,**(undefined8 **)(local_38 + 8),local_220,
               1);
    ::ATCTxon::~ATCTxon((ATCTxon *)local_220);
    pvVar23 = local_40;
    goto LAB_0033c9c6;
  }
LAB_0033c4a9:
  plVar21 = (long *)**(ulong **)(local_38 + 8);
  plVar11 = (long *)*local_48;
  plVar15 = local_48;
  if (plVar11 == (long *)0x0) {
LAB_0033c4f5:
    local_40 = (vec_sta_struct *)(**(code **)(*plVar21 + 0x318))();
    std::string::string((string *)local_220,local_68);
    if ((local_220._0_8_ & 1) != 0) {
      local_b0 = local_210;
    }
    if (local_40 == (vec_sta_struct *)0x0) {
      pcVar17 = "Unknown";
    }
    else {
      pcVar17 = (char *)apt_get_string(*(uint *)(local_40 + 0x1c));
    }
    _source_sim_log_write(3,"ATC",
                      "CreateTaxiRouteToGate failed for %s during an initial routing to gate at %s",
                      local_b0,pcVar17);
    if ((local_220._0_8_ & 1) != 0) {
      operator_delete(local_210);
    }
    (**(code **)(*(long *)**(undefined8 **)(local_38 + 8) + 0x1a8))
              ((long *)**(undefined8 **)(local_38 + 8),
               "Unable to create taxi route to gate because of authoring errors in this airport");
  }
  else {
    do {
      if ((long *)plVar11[4] >= plVar21) {
        plVar15 = plVar11;
      }
      plVar11 = (long *)plVar11[(long *)plVar11[4] < plVar21];
    } while (plVar11 != (long *)0x0);
    if ((plVar15 == local_48) || (plVar21 < (long *)plVar15[4])) goto LAB_0033c4f5;
    (**(code **)(*plVar21 + 0x1a8))
              (plVar21,"Unable to create taxi route to gate because no parking was available.");
  }
  pvVar23 = (vec_sta_struct *)0x0;
LAB_0033c9c6:
  std::
  __tree<vec_sta_struct_const*,std::less<vec_sta_struct_const*>,std::allocator<vec_sta_struct_const*>>
  ::destroy((__tree<vec_sta_struct_const*,std::less<vec_sta_struct_const*>,std::allocator<vec_sta_struct_const*>>
             *)&local_80,(__tree_node *)local_78._0_8_);
  return pvVar23;
}


// 00376830  std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>::~__func

/* std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D,
   std::string&, ATCFlightRoute&)::$_17,
   std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&,
   ATCFlightRoute&)::$_17>, bool ()>::~__func() */

void __thiscall
std::__function::
__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>
::~__func(__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  *(undefined ***)this = &PTR____func_02ad42e8;
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
      return;
    }
  }
  return;
}


// 00376880  std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>::~__func

/* std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D,
   std::string&, ATCFlightRoute&)::$_17,
   std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&,
   ATCFlightRoute&)::$_17>, bool ()>::~__func() */

void __thiscall
std::__function::
__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>
::~__func(__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  *(undefined ***)this = &PTR____func_02ad42e8;
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
    }
  }
  operator_delete(this);
  return;
}


// 003768d0  std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>::__clone

/* std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D,
   std::string&, ATCFlightRoute&)::$_17,
   std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&,
   ATCFlightRoute&)::$_17>, bool ()>::__clone() const */

void __thiscall
std::__function::
__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>
::__clone(__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
          *this)

{
  undefined8 uVar1;
  long lVar2;
  undefined8 *puVar3;
  
  puVar3 = operator_new(0x18);
  uVar1 = *(undefined8 *)(this + 8);
  lVar2 = *(long *)(this + 0x10);
  *puVar3 = &PTR____func_02ad42e8;
  puVar3[1] = uVar1;
  puVar3[2] = lVar2;
  if (lVar2 != 0) {
    LOCK();
    *(long *)(lVar2 + 8) = *(long *)(lVar2 + 8) + 1;
    UNLOCK();
  }
  return;
}


// 00376910  std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>::__clone

/* std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D,
   std::string&, ATCFlightRoute&)::$_17,
   std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&,
   ATCFlightRoute&)::$_17>, bool ()>::__clone(std::__function::__base<bool ()>*) const */

void __thiscall
std::__function::
__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>
::__clone(__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
          *this,__base *param_1)

{
  undefined8 uVar1;
  long lVar2;
  
  uVar1 = *(undefined8 *)(this + 8);
  lVar2 = *(long *)(this + 0x10);
  *(undefined ***)param_1 = &PTR____func_02ad42e8;
  *(undefined8 *)(param_1 + 8) = uVar1;
  *(long *)(param_1 + 0x10) = lVar2;
  if (lVar2 != 0) {
    LOCK();
    *(long *)(lVar2 + 8) = *(long *)(lVar2 + 8) + 1;
    UNLOCK();
  }
  return;
}


// 00376940  std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>::destroy

/* std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D,
   std::string&, ATCFlightRoute&)::$_17,
   std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&,
   ATCFlightRoute&)::$_17>, bool ()>::destroy() */

void __thiscall
std::__function::
__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>
::destroy(__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
      return;
    }
  }
  return;
}


// 00376980  std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>::destroy_deallocate

/* std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D,
   std::string&, ATCFlightRoute&)::$_17,
   std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&,
   ATCFlightRoute&)::$_17>, bool ()>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>
::destroy_deallocate
          (__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
           *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
    }
  }
  operator_delete(this);
  return;
}


// 003769d0  std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>::operator()

/* std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D,
   std::string&, ATCFlightRoute&)::$_17,
   std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&,
   ATCFlightRoute&)::$_17>, bool ()>::TEMPNAMEPLACEHOLDERVALUE() */

undefined8 __thiscall
std::__function::
__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>
::operator()(__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
             *this)

{
  return CONCAT71((int7)((ulong)*(long *)(this + 8) >> 8),*(int *)(*(long *)(this + 8) + 0x4f8) == 4
                 );
}


// 003769f0  std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>::target

/* std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D,
   std::string&, ATCFlightRoute&)::$_17,
   std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&,
   ATCFlightRoute&)::$_17>, bool ()>::target(std::type_info const&) const */

__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
* __thiscall
std::__function::
__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>
::target(__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
         *this,type_info *param_1)

{
  __func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
  *p_Var1;
  
  p_Var1 = (__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::__17>,bool()>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN11ATCAircraft17FileIFRFlightplanER21ATCAircraftFlightPlan10GeoPoint2DRNSt3__112basic_stringIcNS3_11char_traitsIcEENS3_9allocatorIcEEEER14ATCFlightRouteE4$_17"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00376a10  std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>::target_type

/* std::__function::__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D,
   std::string&, ATCFlightRoute&)::$_17,
   std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&, GeoPoint2D, std::string&,
   ATCFlightRoute&)::$_17>, bool ()>::target_type() const */

undefined **
std::__function::
__func<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17,std::allocator<ATCAircraft::FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17>,bool()>
::target_type(void)

{
  return &ATCAircraft::
          FileIFRFlightplan(ATCAircraftFlightPlan&,GeoPoint2D,std::string&,ATCFlightRoute&)::$_17::
          typeinfo;
}


// 0037f530  std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>::~__func

/* std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&,
   ATCFlightRoute const&) const::$_25,
   std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&, ATCFlightRoute
   const&) const::$_25>, bool ()>::~__func() */

void __thiscall
std::__function::
__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>
::~__func(__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  *(undefined ***)this = &PTR____func_02ad4758;
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
      return;
    }
  }
  return;
}


// 0037f580  std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>::~__func

/* std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&,
   ATCFlightRoute const&) const::$_25,
   std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&, ATCFlightRoute
   const&) const::$_25>, bool ()>::~__func() */

void __thiscall
std::__function::
__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>
::~__func(__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  *(undefined ***)this = &PTR____func_02ad4758;
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
    }
  }
  operator_delete(this);
  return;
}


// 0037f5d0  std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>::__clone

/* std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&,
   ATCFlightRoute const&) const::$_25,
   std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&, ATCFlightRoute
   const&) const::$_25>, bool ()>::__clone() const */

void __thiscall
std::__function::
__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>
::__clone(__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
          *this)

{
  undefined8 uVar1;
  long lVar2;
  undefined8 *puVar3;
  
  puVar3 = operator_new(0x18);
  uVar1 = *(undefined8 *)(this + 8);
  lVar2 = *(long *)(this + 0x10);
  *puVar3 = &PTR____func_02ad4758;
  puVar3[1] = uVar1;
  puVar3[2] = lVar2;
  if (lVar2 != 0) {
    LOCK();
    *(long *)(lVar2 + 8) = *(long *)(lVar2 + 8) + 1;
    UNLOCK();
  }
  return;
}


// 0037f610  std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>::__clone

/* std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&,
   ATCFlightRoute const&) const::$_25,
   std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&, ATCFlightRoute
   const&) const::$_25>, bool ()>::__clone(std::__function::__base<bool ()>*) const */

void __thiscall
std::__function::
__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>
::__clone(__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
          *this,__base *param_1)

{
  undefined8 uVar1;
  long lVar2;
  
  uVar1 = *(undefined8 *)(this + 8);
  lVar2 = *(long *)(this + 0x10);
  *(undefined ***)param_1 = &PTR____func_02ad4758;
  *(undefined8 *)(param_1 + 8) = uVar1;
  *(long *)(param_1 + 0x10) = lVar2;
  if (lVar2 != 0) {
    LOCK();
    *(long *)(lVar2 + 8) = *(long *)(lVar2 + 8) + 1;
    UNLOCK();
  }
  return;
}


// 0037f640  std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>::destroy

/* std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&,
   ATCFlightRoute const&) const::$_25,
   std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&, ATCFlightRoute
   const&) const::$_25>, bool ()>::destroy() */

void __thiscall
std::__function::
__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>
::destroy(__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
      return;
    }
  }
  return;
}


// 0037f680  std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>::destroy_deallocate

/* std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&,
   ATCFlightRoute const&) const::$_25,
   std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&, ATCFlightRoute
   const&) const::$_25>, bool ()>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>
::destroy_deallocate
          (__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
           *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
    }
  }
  operator_delete(this);
  return;
}


// 0037f6d0  std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>::operator()

/* std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&,
   ATCFlightRoute const&) const::$_25,
   std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&, ATCFlightRoute
   const&) const::$_25>, bool ()>::TEMPNAMEPLACEHOLDERVALUE() */

undefined8 __thiscall
std::__function::
__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>
::operator()(__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
             *this)

{
  return CONCAT71((int7)((ulong)*(long *)(this + 8) >> 8),*(int *)(*(long *)(this + 8) + 0x4f8) == 4
                 );
}


// 0037f6f0  std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>::target

/* std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&,
   ATCFlightRoute const&) const::$_25,
   std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&, ATCFlightRoute
   const&) const::$_25>, bool ()>::target(std::type_info const&) const */

__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
* __thiscall
std::__function::
__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>
::target(__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
         *this,type_info *param_1)

{
  __func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
  *p_Var1;
  
  p_Var1 = (__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::__25>,bool()>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZNK17ATCSourceAircraft13SendPlanToFMSERK21ATCAircraftFlightPlanRK14ATCFlightRouteE4$_25") {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 0037f710  std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>::target_type

/* std::__function::__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&,
   ATCFlightRoute const&) const::$_25,
   std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan const&, ATCFlightRoute
   const&) const::$_25>, bool ()>::target_type() const */

undefined **
std::__function::
__func<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25,std::allocator<ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)const::$_25>,bool()>
::target_type(void)

{
  return &ATCSourceAircraft::SendPlanToFMS(ATCAircraftFlightPlan_const&,ATCFlightRoute_const&)::
          typeinfo;
}


// 00381c80  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_41, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_41>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00381c90  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_41, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_41>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00381ca0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_41, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_41>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  undefined8 *puVar2;
  
  puVar2 = operator_new(0x18);
  *puVar2 = &PTR____func_02ad4c18;
  uVar1 = *(undefined8 *)(this + 0x10);
  puVar2[1] = *(undefined8 *)(this + 8);
  puVar2[2] = uVar1;
  return;
}


// 00381cd0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_41, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_41>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  
  *(undefined ***)param_1 = &PTR____func_02ad4c18;
  uVar1 = *(undefined8 *)(this + 0x10);
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  *(undefined8 *)(param_1 + 0x10) = uVar1;
  return;
}


// 00381cf0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_41, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_41>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00381d00  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_41, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_41>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00381d10  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_41, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_41>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  code *UNRECOVERED_JUMPTABLE;
  
  if (*param_2 != false) {
    UNRECOVERED_JUMPTABLE = *(code **)(*(long *)*param_1 + 0x68);
                    /* WARNING: Could not recover jumptable at 0x00381d33. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*UNRECOVERED_JUMPTABLE)
              (*(undefined4 *)(this + 8),*param_1,*(undefined8 *)(this + 0xc),
               *(undefined4 *)(this + 0x14),UNRECOVERED_JUMPTABLE);
    return;
  }
  return;
}


// 00381d40  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_41, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_41>, void (ATCAircraft*, bool)>::target(std::type_info
   const&) const */

__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__41>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController20IssueTurnIfNecessaryEP11ATCAircraftPK16ATCFlightSegmentR7ATCTxonE4$_41") {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00381d60  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_41, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_41>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_41::
          typeinfo;
}


// 00381d70  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_42, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_42>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00381d80  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_42, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_42>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00381d90  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_42, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_42>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  undefined8 *puVar2;
  
  puVar2 = operator_new(0x18);
  *puVar2 = &PTR____func_02ad4c98;
  uVar1 = *(undefined8 *)(this + 0x10);
  puVar2[1] = *(undefined8 *)(this + 8);
  puVar2[2] = uVar1;
  return;
}


// 00381dc0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_42, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_42>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  
  *(undefined ***)param_1 = &PTR____func_02ad4c98;
  uVar1 = *(undefined8 *)(this + 0x10);
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  *(undefined8 *)(param_1 + 0x10) = uVar1;
  return;
}


// 00381de0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_42, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_42>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00381df0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_42, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_42>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00381e00  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_42, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_42>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  code *UNRECOVERED_JUMPTABLE;
  
  if (*param_2 != false) {
    UNRECOVERED_JUMPTABLE = *(code **)(*(long *)*param_1 + 0x68);
                    /* WARNING: Could not recover jumptable at 0x00381e23. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*UNRECOVERED_JUMPTABLE)
              (*(undefined4 *)(this + 8),*param_1,*(undefined8 *)(this + 0xc),
               *(undefined4 *)(this + 0x14),UNRECOVERED_JUMPTABLE);
    return;
  }
  return;
}


// 00381e30  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_42, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_42>, void (ATCAircraft*, bool)>::target(std::type_info
   const&) const */

__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__42>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController20IssueTurnIfNecessaryEP11ATCAircraftPK16ATCFlightSegmentR7ATCTxonE4$_42") {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00381e50  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_42, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_42>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_42::
          typeinfo;
}


// 00381e60  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_43, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_43>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00381e70  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_43, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_43>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00381e80  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_43, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_43>, void (ATCAircraft*, bool)>::__clone() const */

void std::__function::
     __func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>
     ::__clone(void)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02ad4d18;
  return;
}


// 00381ea0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_43, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_43>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02ad4d18;
  return;
}


// 00381eb0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_43, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_43>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00381ec0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_43, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_43>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00381ed0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_43, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_43>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  if (*param_2 != false) {
                    /* WARNING: Could not recover jumptable at 0x00381ee0. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (**(code **)(*(long *)*param_1 + 0x20))();
    return;
  }
  return;
}


// 00381ef0  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_43, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_43>, void (ATCAircraft*, bool)>::target(std::type_info
   const&) const */

__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__43>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController20IssueTurnIfNecessaryEP11ATCAircraftPK16ATCFlightSegmentR7ATCTxonE4$_43") {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00381f10  std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueTurnIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_43, std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_43>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43,std::allocator<ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueTurnIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_43::
          typeinfo;
}


// 00381f20  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_45, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_45>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00381f30  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_45, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_45>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00381f40  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_45, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_45>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02ad4d98;
  *(undefined4 *)(puVar1 + 1) = *(undefined4 *)(this + 8);
  return;
}


// 00381f70  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_45, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_45>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02ad4d98;
  *(undefined4 *)(param_1 + 8) = *(undefined4 *)(this + 8);
  return;
}


// 00381f90  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_45, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_45>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00381fa0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_45, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_45>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00381fb0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_45, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_45>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  code *UNRECOVERED_JUMPTABLE;
  
  if (*param_2 != false) {
    UNRECOVERED_JUMPTABLE = *(code **)(*(long *)*param_1 + 200);
                    /* WARNING: Could not recover jumptable at 0x00381fd3. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*UNRECOVERED_JUMPTABLE)(*(undefined4 *)(this + 8),*param_1,0,0,UNRECOVERED_JUMPTABLE);
    return;
  }
  return;
}


// 00381fe0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_45, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_45>, void (ATCAircraft*, bool)>::target(std::type_info
   const&) const */

__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__45>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController21IssueSpeedIfNecessaryEP11ATCAircraftPK16ATCFlightSegmentR7ATCTxonE4$_45")
  {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00382000  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_45, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_45>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_45
          ::typeinfo;
}


// 00382010  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_46, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_46>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00382020  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_46, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_46>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00382030  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_46, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_46>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02ad4e18;
  *(undefined4 *)(puVar1 + 1) = *(undefined4 *)(this + 8);
  return;
}


// 00382060  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_46, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_46>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02ad4e18;
  *(undefined4 *)(param_1 + 8) = *(undefined4 *)(this + 8);
  return;
}


// 00382080  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_46, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_46>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00382090  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_46, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_46>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 003820a0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_46, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_46>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  code *UNRECOVERED_JUMPTABLE;
  
  if (*param_2 != false) {
    UNRECOVERED_JUMPTABLE = *(code **)(*(long *)*param_1 + 200);
                    /* WARNING: Could not recover jumptable at 0x003820c6. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*UNRECOVERED_JUMPTABLE)(*(undefined4 *)(this + 8),*param_1,1,0,UNRECOVERED_JUMPTABLE);
    return;
  }
  return;
}


// 003820d0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_46, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_46>, void (ATCAircraft*, bool)>::target(std::type_info
   const&) const */

__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__46>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController21IssueSpeedIfNecessaryEP11ATCAircraftPK16ATCFlightSegmentR7ATCTxonE4$_46")
  {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 003820f0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_46, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_46>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_46
          ::typeinfo;
}


// 00382100  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_47, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_47>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00382110  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_47, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_47>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00382120  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_47, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_47>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02ad4e98;
  *(undefined4 *)(puVar1 + 1) = *(undefined4 *)(this + 8);
  return;
}


// 00382150  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_47, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_47>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02ad4e98;
  *(undefined4 *)(param_1 + 8) = *(undefined4 *)(this + 8);
  return;
}


// 00382170  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_47, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_47>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00382180  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_47, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_47>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00382190  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_47, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_47>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  code *UNRECOVERED_JUMPTABLE;
  
  if (*param_2 != false) {
    UNRECOVERED_JUMPTABLE = *(code **)(*(long *)*param_1 + 200);
                    /* WARNING: Could not recover jumptable at 0x003821b6. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*UNRECOVERED_JUMPTABLE)(*(undefined4 *)(this + 8),*param_1,0,1,UNRECOVERED_JUMPTABLE);
    return;
  }
  return;
}


// 003821c0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_47, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_47>, void (ATCAircraft*, bool)>::target(std::type_info
   const&) const */

__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__47>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController21IssueSpeedIfNecessaryEP11ATCAircraftPK16ATCFlightSegmentR7ATCTxonE4$_47")
  {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 003821e0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_47, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_47>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_47
          ::typeinfo;
}


// 003821f0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_48, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_48>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00382200  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_48, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_48>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00382210  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_48, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_48>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02ad4f18;
  puVar1[1] = *(undefined8 *)(this + 8);
  return;
}


// 00382240  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_48, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_48>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02ad4f18;
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  return;
}


// 00382260  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_48, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_48>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00382270  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_48, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_48>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00382280  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_48, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_48>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  code *UNRECOVERED_JUMPTABLE;
  
  if (*param_2 != false) {
    UNRECOVERED_JUMPTABLE = *(code **)(*(long *)*param_1 + 0xe8);
                    /* WARNING: Could not recover jumptable at 0x003822a4. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*UNRECOVERED_JUMPTABLE)
              (*(undefined4 *)(this + 8),*(undefined4 *)(this + 0xc),*param_1,param_1,param_2,
               UNRECOVERED_JUMPTABLE);
    return;
  }
  return;
}


// 003822b0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_48, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_48>, void (ATCAircraft*, bool)>::target(std::type_info
   const&) const */

__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__48>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController21IssueSpeedIfNecessaryEP11ATCAircraftPK16ATCFlightSegmentR7ATCTxonE4$_48")
  {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 003822d0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_48, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_48>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_48
          ::typeinfo;
}


// 003822e0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_49, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_49>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 003822f0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_49, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_49>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00382300  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_49, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_49>, void (ATCAircraft*, bool)>::__clone() const */

void std::__function::
     __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>
     ::__clone(void)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02ad4f98;
  return;
}


// 00382320  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_49, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_49>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02ad4f98;
  return;
}


// 00382330  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_49, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_49>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00382340  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_49, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_49>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00382350  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_49, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_49>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  if (*param_2 != false) {
                    /* WARNING: Could not recover jumptable at 0x00382374. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (**(code **)(*(long *)*param_1 + 200))(0,*param_1,1,1);
    return;
  }
  return;
}


// 00382380  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_49, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_49>, void (ATCAircraft*, bool)>::target(std::type_info
   const&) const */

__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::__49>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController21IssueSpeedIfNecessaryEP11ATCAircraftPK16ATCFlightSegmentR7ATCTxonE4$_49")
  {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 003823a0  std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*, ATCFlightSegment
   const*, ATCTxon&)::$_49, std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,
   ATCFlightSegment const*, ATCTxon&)::$_49>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49,std::allocator<ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueSpeedIfNecessary(ATCAircraft*,ATCFlightSegment_const*,ATCTxon&)::$_49
          ::typeinfo;
}


// 003823b0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_50,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_50>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  *(undefined ***)this = &PTR____func_02ad5018;
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
      return;
    }
  }
  return;
}


// 00382400  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_50,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_50>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  *(undefined ***)this = &PTR____func_02ad5018;
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
    }
  }
  operator_delete(this);
  return;
}


// 00382450  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_50,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_50>, void (ATCAircraft*, bool)>::__clone()
   const */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  long lVar2;
  undefined8 *puVar3;
  
  puVar3 = operator_new(0x18);
  uVar1 = *(undefined8 *)(this + 8);
  lVar2 = *(long *)(this + 0x10);
  *puVar3 = &PTR____func_02ad5018;
  puVar3[1] = uVar1;
  puVar3[2] = lVar2;
  if (lVar2 != 0) {
    LOCK();
    *(long *)(lVar2 + 8) = *(long *)(lVar2 + 8) + 1;
    UNLOCK();
  }
  return;
}


// 00382490  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_50,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_50>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  long lVar2;
  
  uVar1 = *(undefined8 *)(this + 8);
  lVar2 = *(long *)(this + 0x10);
  *(undefined ***)param_1 = &PTR____func_02ad5018;
  *(undefined8 *)(param_1 + 8) = uVar1;
  *(long *)(param_1 + 0x10) = lVar2;
  if (lVar2 != 0) {
    LOCK();
    *(long *)(lVar2 + 8) = *(long *)(lVar2 + 8) + 1;
    UNLOCK();
  }
  return;
}


// 003824c0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_50,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_50>, void (ATCAircraft*, bool)>::destroy() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>
::destroy(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
      return;
    }
  }
  return;
}


// 00382500  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_50,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_50>, void (ATCAircraft*,
   bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
           *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
    }
  }
  operator_delete(this);
  return;
}


// 00382550  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_50,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_50>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  if (*param_2 != false) {
    ATCController::HandleReportFieldInSight(*(ATCAircraft **)(this + 8),SUB81(*param_1,0));
    return;
  }
  return;
}


// 00382570  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_50,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_50>, void (ATCAircraft*,
   bool)>::target(std::type_info const&) const */

__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__50>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZNK13ATCController23IssueHandoffIfNecessaryEPK11ATCAircraftPK16ATCFlightSegmentS5_R7ATCTxonE4$_50"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00382590  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_50,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_50>, void (ATCAircraft*,
   bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_50>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::
          IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)
          ::typeinfo;
}


// 003825a0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_51,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_51>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 003825b0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_51,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_51>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 003825c0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_51,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_51>, void (ATCAircraft*, bool)>::__clone()
   const */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  undefined8 *puVar2;
  
  puVar2 = operator_new(0x20);
  *puVar2 = &PTR____func_02ad5098;
  uVar1 = *(undefined8 *)(this + 0x10);
  puVar2[1] = *(undefined8 *)(this + 8);
  puVar2[2] = uVar1;
  puVar2[3] = *(undefined8 *)(this + 0x18);
  return;
}


// 00382600  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_51,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_51>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  
  *(undefined ***)param_1 = &PTR____func_02ad5098;
  uVar1 = *(undefined8 *)(this + 0x10);
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  *(undefined8 *)(param_1 + 0x10) = uVar1;
  *(undefined8 *)(param_1 + 0x18) = *(undefined8 *)(this + 0x18);
  return;
}


// 00382620  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_51,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_51>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00382630  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_51,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_51>, void (ATCAircraft*,
   bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00382640  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_51,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_51>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  long *plVar1;
  ATCAircraft *pAVar2;
  long lVar3;
  long *plVar4;
  ATCControllerCab *this_00;
  long *plVar5;
  
  if (*param_2 != false) {
    pAVar2 = *param_1;
    lVar3 = *(long *)(pAVar2 + 0x2d8);
    plVar4 = *(long **)(pAVar2 + 0x2e0);
    if (plVar4 != (long *)0x0) {
      LOCK();
      plVar4[1] = plVar4[1] + 1;
      UNLOCK();
    }
    if ((lVar3 != 0) &&
       (this_00 = *(ATCControllerCab **)(lVar3 + 0x1d0), this_00 != (ATCControllerCab *)0x0)) {
      plVar5 = *(long **)(lVar3 + 0x1d8);
      if (plVar5 != (long *)0x0) {
        LOCK();
        plVar5[1] = plVar5[1] + 1;
        UNLOCK();
      }
      ATCControllerCab::InsertAircraftIntoActiveBucket(this_00,pAVar2);
      if (plVar5 != (long *)0x0) {
        LOCK();
        plVar1 = plVar5 + 1;
        lVar3 = *plVar1;
        *plVar1 = *plVar1 + -1;
        UNLOCK();
        if (lVar3 == 0) {
          (**(code **)(*plVar5 + 0x10))(plVar5);
          std::__shared_weak_count::__release_weak();
        }
      }
    }
    (**(code **)(*(long *)pAVar2 + 0x118))(pAVar2,*(undefined8 *)(this + 8),this + 0x10);
    if (plVar4 != (long *)0x0) {
      LOCK();
      plVar5 = plVar4 + 1;
      lVar3 = *plVar5;
      *plVar5 = *plVar5 + -1;
      UNLOCK();
      if (lVar3 == 0) {
        (**(code **)(*plVar4 + 0x10))(plVar4);
        std::__shared_weak_count::__release_weak();
        return;
      }
    }
  }
  return;
}


// 00382780  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_51,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_51>, void (ATCAircraft*,
   bool)>::target(std::type_info const&) const */

__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__51>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZNK13ATCController23IssueHandoffIfNecessaryEPK11ATCAircraftPK16ATCFlightSegmentS5_R7ATCTxonE4$_51"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 003827a0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_51,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_51>, void (ATCAircraft*,
   bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_51>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::
          IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)
          ::typeinfo;
}


// 003827b0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_52,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_52>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  *(undefined ***)this = &PTR____func_02ad5118;
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
      return;
    }
  }
  return;
}


// 00382800  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_52,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_52>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  *(undefined ***)this = &PTR____func_02ad5118;
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
    }
  }
  operator_delete(this);
  return;
}


// 00382850  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_52,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_52>, void (ATCAircraft*, bool)>::__clone()
   const */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  long lVar2;
  undefined8 *puVar3;
  
  puVar3 = operator_new(0x18);
  uVar1 = *(undefined8 *)(this + 8);
  lVar2 = *(long *)(this + 0x10);
  *puVar3 = &PTR____func_02ad5118;
  puVar3[1] = uVar1;
  puVar3[2] = lVar2;
  if (lVar2 != 0) {
    LOCK();
    *(long *)(lVar2 + 8) = *(long *)(lVar2 + 8) + 1;
    UNLOCK();
  }
  return;
}


// 00382890  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_52,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_52>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  long lVar2;
  
  uVar1 = *(undefined8 *)(this + 8);
  lVar2 = *(long *)(this + 0x10);
  *(undefined ***)param_1 = &PTR____func_02ad5118;
  *(undefined8 *)(param_1 + 8) = uVar1;
  *(long *)(param_1 + 0x10) = lVar2;
  if (lVar2 != 0) {
    LOCK();
    *(long *)(lVar2 + 8) = *(long *)(lVar2 + 8) + 1;
    UNLOCK();
  }
  return;
}


// 003828c0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_52,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_52>, void (ATCAircraft*, bool)>::destroy() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>
::destroy(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
          *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
      return;
    }
  }
  return;
}


// 00382900  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_52,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_52>, void (ATCAircraft*,
   bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
           *this)

{
  long *plVar1;
  long lVar2;
  long *plVar3;
  
  plVar3 = *(long **)(this + 0x10);
  if (plVar3 != (long *)0x0) {
    LOCK();
    plVar1 = plVar3 + 1;
    lVar2 = *plVar1;
    *plVar1 = *plVar1 + -1;
    UNLOCK();
    if (lVar2 == 0) {
      (**(code **)(*plVar3 + 0x10))(plVar3);
      std::__shared_weak_count::__release_weak();
    }
  }
  operator_delete(this);
  return;
}


// 00382950  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_52,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_52>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  if (*param_2 != false) {
    ATCController::HandleReportOnLocaliser(*(ATCAircraft **)(this + 8),SUB81(*param_1,0));
    return;
  }
  return;
}


// 00382970  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_52,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_52>, void (ATCAircraft*,
   bool)>::target(std::type_info const&) const */

__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__52>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZNK13ATCController23IssueHandoffIfNecessaryEPK11ATCAircraftPK16ATCFlightSegmentS5_R7ATCTxonE4$_52"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00382990  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_52,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_52>, void (ATCAircraft*,
   bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_52>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::
          IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)
          ::typeinfo;
}


// 003829a0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_53,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_53>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 003829b0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_53,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_53>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 003829c0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_53,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_53>, void (ATCAircraft*, bool)>::__clone()
   const */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  undefined8 *puVar2;
  
  puVar2 = operator_new(0x20);
  *puVar2 = &PTR____func_02ad5198;
  uVar1 = *(undefined8 *)(this + 0x10);
  puVar2[1] = *(undefined8 *)(this + 8);
  puVar2[2] = uVar1;
  puVar2[3] = *(undefined8 *)(this + 0x18);
  return;
}


// 00382a00  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_53,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_53>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  
  *(undefined ***)param_1 = &PTR____func_02ad5198;
  uVar1 = *(undefined8 *)(this + 0x10);
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  *(undefined8 *)(param_1 + 0x10) = uVar1;
  *(undefined8 *)(param_1 + 0x18) = *(undefined8 *)(this + 0x18);
  return;
}


// 00382a20  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_53,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_53>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00382a30  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_53,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_53>, void (ATCAircraft*,
   bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00382a40  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_53,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_53>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  long *plVar1;
  ATCAircraft *pAVar2;
  long lVar3;
  long *plVar4;
  ATCControllerCab *this_00;
  long *plVar5;
  
  if (*param_2 != false) {
    pAVar2 = *param_1;
    lVar3 = *(long *)(pAVar2 + 0x2d8);
    plVar4 = *(long **)(pAVar2 + 0x2e0);
    if (plVar4 != (long *)0x0) {
      LOCK();
      plVar4[1] = plVar4[1] + 1;
      UNLOCK();
    }
    if ((lVar3 != 0) &&
       (this_00 = *(ATCControllerCab **)(lVar3 + 0x1d0), this_00 != (ATCControllerCab *)0x0)) {
      plVar5 = *(long **)(lVar3 + 0x1d8);
      if (plVar5 != (long *)0x0) {
        LOCK();
        plVar5[1] = plVar5[1] + 1;
        UNLOCK();
      }
      ATCControllerCab::InsertAircraftIntoActiveBucket(this_00,pAVar2);
      if (plVar5 != (long *)0x0) {
        LOCK();
        plVar1 = plVar5 + 1;
        lVar3 = *plVar1;
        *plVar1 = *plVar1 + -1;
        UNLOCK();
        if (lVar3 == 0) {
          (**(code **)(*plVar5 + 0x10))(plVar5);
          std::__shared_weak_count::__release_weak();
        }
      }
    }
    (**(code **)(*(long *)pAVar2 + 0x110))(pAVar2,*(undefined8 *)(this + 8),this + 0x10);
    if (plVar4 != (long *)0x0) {
      LOCK();
      plVar5 = plVar4 + 1;
      lVar3 = *plVar5;
      *plVar5 = *plVar5 + -1;
      UNLOCK();
      if (lVar3 == 0) {
        (**(code **)(*plVar4 + 0x10))(plVar4);
        std::__shared_weak_count::__release_weak();
        return;
      }
    }
  }
  return;
}


// 00382b80  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_53,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_53>, void (ATCAircraft*,
   bool)>::target(std::type_info const&) const */

__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::__53>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZNK13ATCController23IssueHandoffIfNecessaryEPK11ATCAircraftPK16ATCFlightSegmentS5_R7ATCTxonE4$_53"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00382ba0  std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueHandoffIfNecessary(ATCAircraft const*,
   ATCFlightSegment const*, ATCFlightSegment const*, ATCTxon&) const::$_53,
   std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft const*, ATCFlightSegment
   const*, ATCFlightSegment const*, ATCTxon&) const::$_53>, void (ATCAircraft*,
   bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53,std::allocator<ATCController::IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)const::$_53>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::
          IssueHandoffIfNecessary(ATCAircraft_const*,ATCFlightSegment_const*,ATCFlightSegment_const*,ATCTxon&)
          ::typeinfo;
}


// 00383580  std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment const*, ATCFlightSegment
   const*, bool, ATCTxon&)::$_58, std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment
   const*, ATCFlightSegment const*, bool, ATCTxon&)::$_58>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00383590  std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment const*, ATCFlightSegment
   const*, bool, ATCTxon&)::$_58, std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment
   const*, ATCFlightSegment const*, bool, ATCTxon&)::$_58>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 003835a0  std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment const*, ATCFlightSegment
   const*, bool, ATCTxon&)::$_58, std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment
   const*, ATCFlightSegment const*, bool, ATCTxon&)::$_58>, void (ATCAircraft*, bool)>::__clone()
   const */

void std::__function::
     __func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>
     ::__clone(void)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02ad5398;
  return;
}


// 003835c0  std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment const*, ATCFlightSegment
   const*, bool, ATCTxon&)::$_58, std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment
   const*, ATCFlightSegment const*, bool, ATCTxon&)::$_58>, void (ATCAircraft*,
   bool)>::__clone(std::__function::__base<void (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02ad5398;
  return;
}


// 003835d0  std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment const*, ATCFlightSegment
   const*, bool, ATCTxon&)::$_58, std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment
   const*, ATCFlightSegment const*, bool, ATCTxon&)::$_58>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 003835e0  std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment const*, ATCFlightSegment
   const*, bool, ATCTxon&)::$_58, std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment
   const*, ATCFlightSegment const*, bool, ATCTxon&)::$_58>, void (ATCAircraft*,
   bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 003835f0  std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment const*, ATCFlightSegment
   const*, bool, ATCTxon&)::$_58, std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment
   const*, ATCFlightSegment const*, bool, ATCTxon&)::$_58>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void std::__function::
     __func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>
     ::operator()(ATCAircraft **param_1,bool *param_2)

{
  return;
}


// 00383600  std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment const*, ATCFlightSegment
   const*, bool, ATCTxon&)::$_58, std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment
   const*, ATCFlightSegment const*, bool, ATCTxon&)::$_58>, void (ATCAircraft*,
   bool)>::target(std::type_info const&) const */

__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>
::target(__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::__58>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController16CrossRunwaysUpToEPK16ATCFlightSegmentS2_bR7ATCTxonE4$_58") {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00383620  std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment const*, ATCFlightSegment
   const*, bool, ATCTxon&)::$_58, std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment
   const*, ATCFlightSegment const*, bool, ATCTxon&)::$_58>, void (ATCAircraft*,
   bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58,std::allocator<ATCController::CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::
          CrossRunwaysUpTo(ATCFlightSegment_const*,ATCFlightSegment_const*,bool,ATCTxon&)::$_58::
          typeinfo;
}


// 003842a0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 003842b0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 003842c0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 *puVar1;
  
  puVar1 = operator_new(0x10);
  *puVar1 = &PTR____func_02ad5818;
  puVar1[1] = *(undefined8 *)(this + 8);
  return;
}


// 003842f0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67>, void (ATCAircraft*, bool)>::__clone(std::__function::__base<void
   (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  *(undefined ***)param_1 = &PTR____func_02ad5818;
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  return;
}


// 00384310  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00384320  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00384330  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  undefined4 local_20;
  undefined4 local_1c;
  undefined1 local_18;
  undefined4 local_14;
  undefined1 local_10;
  
  if (*param_2 != false) {
    local_1c = *(undefined4 *)(this + 8);
    local_20 = 0;
    local_18 = 1;
    local_10 = 1;
    local_14 = local_1c;
    (**(code **)(*(long *)*param_1 + 0x78))(*(undefined4 *)(this + 0xc),*param_1,&local_20,0,0);
  }
  return;
}


// 00384380  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67>, void (ATCAircraft*, bool)>::target(std::type_info const&) const
    */

__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__67>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController22IssueAltitudeClearanceEP11ATCAircraftR7ATCTxonbPK16ATCFlightSegmentE4$_67"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 003843a0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_67>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_67>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)
          ::$_67::typeinfo;
}


// 003843b0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 003843c0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 003843d0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  undefined8 uVar2;
  undefined8 uVar3;
  undefined8 *puVar4;
  
  puVar4 = operator_new(0x30);
  *puVar4 = &PTR____func_02ad5898;
  uVar1 = *(undefined8 *)(this + 0x10);
  uVar2 = *(undefined8 *)(this + 0x18);
  uVar3 = *(undefined8 *)(this + 0x20);
  puVar4[1] = *(undefined8 *)(this + 8);
  puVar4[2] = uVar1;
  puVar4[3] = uVar2;
  puVar4[4] = uVar3;
  puVar4[5] = *(undefined8 *)(this + 0x28);
  return;
}


// 00384410  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68>, void (ATCAircraft*, bool)>::__clone(std::__function::__base<void
   (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  undefined8 uVar2;
  undefined8 uVar3;
  
  *(undefined ***)param_1 = &PTR____func_02ad5898;
  uVar1 = *(undefined8 *)(this + 0x10);
  uVar2 = *(undefined8 *)(this + 0x18);
  uVar3 = *(undefined8 *)(this + 0x20);
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  *(undefined8 *)(param_1 + 0x10) = uVar1;
  *(undefined8 *)(param_1 + 0x18) = uVar2;
  *(undefined8 *)(param_1 + 0x20) = uVar3;
  *(undefined8 *)(param_1 + 0x28) = *(undefined8 *)(this + 0x28);
  return;
}


// 00384440  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 00384450  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 00384460  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  ATCAircraft *pAVar1;
  ATCWaypoint *this_00;
  undefined8 uVar2;
  undefined8 local_38;
  undefined8 uStack_30;
  
  if (*param_2 != false) {
    pAVar1 = *param_1;
    this_00 = *(ATCWaypoint **)(this + 0x20);
    if ((this_00 == (ATCWaypoint *)0x0) ||
       (this_00[0x54] == (ATCWaypoint)0x0 && this_00[0x5c] == (ATCWaypoint)0x0)) {
                    /* WARNING: Could not recover jumptable at 0x003844af. Too many branches */
                    /* WARNING: Treating indirect jump as call */
      (**(code **)(*(long *)pAVar1 + 0x78))
                (*(undefined4 *)(this + 0x2c),pAVar1,this + 8,this[0x28],0);
      return;
    }
    uVar2 = ATCWaypoint::GetGeoCoords(this_00);
    local_38 = *(undefined8 *)(*(long *)(this + 0x20) + 0x50);
    uStack_30 = *(undefined8 *)(*(long *)(this + 0x20) + 0x58);
    (**(code **)(*(long *)pAVar1 + 0xa0))
              (*(undefined4 *)(this + 0x2c),pAVar1,this + 8,uVar2,&local_38,this[0x28]);
  }
  return;
}


// 003844f0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68>, void (ATCAircraft*, bool)>::target(std::type_info const&) const
    */

__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__68>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController22IssueAltitudeClearanceEP11ATCAircraftR7ATCTxonbPK16ATCFlightSegmentE4$_68"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00384510  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_68>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_68>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)
          ::$_68::typeinfo;
}


// 00384520  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00384530  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00384540  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  undefined8 *puVar2;
  
  puVar2 = operator_new(0x20);
  *puVar2 = &PTR____func_02ad5918;
  uVar1 = *(undefined8 *)(this + 0x10);
  puVar2[1] = *(undefined8 *)(this + 8);
  puVar2[2] = uVar1;
  puVar2[3] = *(undefined8 *)(this + 0x18);
  return;
}


// 00384580  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69>, void (ATCAircraft*, bool)>::__clone(std::__function::__base<void
   (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  
  *(undefined ***)param_1 = &PTR____func_02ad5918;
  uVar1 = *(undefined8 *)(this + 0x10);
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  *(undefined8 *)(param_1 + 0x10) = uVar1;
  *(undefined8 *)(param_1 + 0x18) = *(undefined8 *)(this + 0x18);
  return;
}


// 003845a0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 003845b0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 003845c0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  code *UNRECOVERED_JUMPTABLE;
  
  if (*param_2 != false) {
    UNRECOVERED_JUMPTABLE = *(code **)(*(long *)*param_1 + 0x110);
                    /* WARNING: Could not recover jumptable at 0x003845e5. Too many branches */
                    /* WARNING: Treating indirect jump as call */
    (*UNRECOVERED_JUMPTABLE)(*param_1,*(undefined8 *)(this + 8),this + 0x10,UNRECOVERED_JUMPTABLE);
    return;
  }
  return;
}


// 003845f0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69>, void (ATCAircraft*, bool)>::target(std::type_info const&) const
    */

__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__69>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController22IssueAltitudeClearanceEP11ATCAircraftR7ATCTxonbPK16ATCFlightSegmentE4$_69"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00384610  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_69>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_69>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)
          ::$_69::typeinfo;
}


// 00384620  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00384630  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00384640  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  undefined8 *puVar2;
  
  puVar2 = operator_new(0x18);
  *puVar2 = &PTR____func_02ad5998;
  uVar1 = *(undefined8 *)(this + 0x10);
  puVar2[1] = *(undefined8 *)(this + 8);
  puVar2[2] = uVar1;
  return;
}


// 00384670  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70>, void (ATCAircraft*, bool)>::__clone(std::__function::__base<void
   (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  
  *(undefined ***)param_1 = &PTR____func_02ad5998;
  uVar1 = *(undefined8 *)(this + 0x10);
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  *(undefined8 *)(param_1 + 0x10) = uVar1;
  return;
}


// 00384690  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 003846a0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 003846b0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  undefined4 local_20;
  undefined4 local_1c;
  undefined1 local_18;
  undefined4 local_14;
  undefined1 local_10;
  
  if (*param_2 != false) {
    local_1c = *(undefined4 *)(this + 8);
    local_14 = *(undefined4 *)(this + 0xc);
    local_20 = 2;
    local_18 = 1;
    local_10 = 1;
    (**(code **)(*(long *)*param_1 + 0x78))
              (*(undefined4 *)(this + 0x14),*param_1,&local_20,this[0x10],0);
  }
  return;
}


// 00384700  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>::target

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70>, void (ATCAircraft*, bool)>::target(std::type_info const&) const
    */

__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
* __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>
::target(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
         *this,type_info *param_1)

{
  __func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
  *p_Var1;
  
  p_Var1 = (__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__70>,void(ATCAircraft*,bool)>
            *)0x0;
  if (*(char **)(param_1 + 8) ==
      "ZN13ATCController22IssueAltitudeClearanceEP11ATCAircraftR7ATCTxonbPK16ATCFlightSegmentE4$_70"
     ) {
    p_Var1 = this + 8;
  }
  return p_Var1;
}


// 00384720  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>::target_type

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_70>, void (ATCAircraft*, bool)>::target_type() const */

undefined **
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_70>,void(ATCAircraft*,bool)>
::target_type(void)

{
  return &ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)
          ::$_70::typeinfo;
}


// 00384730  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71>,void(ATCAircraft*,bool)>
          *this)

{
  return;
}


// 00384740  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>::~__func

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71>, void (ATCAircraft*, bool)>::~__func() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>
::~__func(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71>,void(ATCAircraft*,bool)>
          *this)

{
  operator_delete(this);
  return;
}


// 00384750  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71>, void (ATCAircraft*, bool)>::__clone() const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71>,void(ATCAircraft*,bool)>
          *this)

{
  undefined8 uVar1;
  undefined8 *puVar2;
  
  puVar2 = operator_new(0x18);
  *puVar2 = &PTR____func_02ad5a18;
  uVar1 = *(undefined8 *)(this + 0x10);
  puVar2[1] = *(undefined8 *)(this + 8);
  puVar2[2] = uVar1;
  return;
}


// 00384780  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>::__clone

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71>, void (ATCAircraft*, bool)>::__clone(std::__function::__base<void
   (ATCAircraft*, bool)>*) const */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>
::__clone(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71>,void(ATCAircraft*,bool)>
          *this,__base *param_1)

{
  undefined8 uVar1;
  
  *(undefined ***)param_1 = &PTR____func_02ad5a18;
  uVar1 = *(undefined8 *)(this + 0x10);
  *(undefined8 *)(param_1 + 8) = *(undefined8 *)(this + 8);
  *(undefined8 *)(param_1 + 0x10) = uVar1;
  return;
}


// 003847a0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>::destroy

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71>, void (ATCAircraft*, bool)>::destroy() */

void std::__function::
     __func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>
     ::destroy(void)

{
  return;
}


// 003847b0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>::destroy_deallocate

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71>, void (ATCAircraft*, bool)>::destroy_deallocate() */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>
::destroy_deallocate
          (__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71>,void(ATCAircraft*,bool)>
           *this)

{
  operator_delete(this);
  return;
}


// 003847c0  std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>::operator()

/* std::__function::__func<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71,
   std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*, ATCTxon&, bool,
   ATCFlightSegment const*)::$_71>, void (ATCAircraft*,
   bool)>::TEMPNAMEPLACEHOLDERVALUE(ATCAircraft*&&, bool&&) */

void __thiscall
std::__function::
__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::$_71>,void(ATCAircraft*,bool)>
::operator()(__func<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71,std::allocator<ATCController::IssueAltitudeClearance(ATCAircraft*,ATCTxon&,bool,ATCFlightSegment_const*)::__71>,void(ATCAircraft*,bool)>
             *this,ATCAircraft **param_1,bool *param_2)

{
  undefined4 local_20;
  undefined4 local_1c;
  undefined1 local_18;
  undefined4 local_14;
  undefined1 local_10;
  
  if (*param_2 != false) {
    local_1c = *(undefined4 *)(this + 8);
    local_14 = *(undefined4 *)(this + 0xc);
    local_20 = 3;
    local_18 = 1;
    local_10 = 1;
    (**(code **)(*(long *)*param_1 + 0x78))
              (*(undefined4 *)(this + 0x14),*param_1,&local_20,this[0x10],0);
  }
  return;
}


