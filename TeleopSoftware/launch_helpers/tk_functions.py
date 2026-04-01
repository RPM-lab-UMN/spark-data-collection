from teleop_runtime_controller import (
    BUTTON_NAMES,
    connect_arm,
    connect_dashboard,
    emergency_stop as controller_emergency_stop,
    freedrive_state,
    ft_home as controller_ft_home,
    gripper_state,
    home_arm,
    init_button_colors,
    invert_space_mouse,
    reset_estop,
    toggle_freedrive,
    toggle_gripper,
    zero_ft,
)

freedrive = freedrive_state
gripper = gripper_state
buttons = BUTTON_NAMES


def db_connect(arm, fields, URs, colors):
    return connect_dashboard(arm, fields, URs, colors)


def db_reset(arm, fields, URs, colors, control_modes, pubs, enable_control):
    return reset_estop(arm, fields, URs, colors, control_modes, pubs, enable_control)


def connect_fun(arm, fields, URs, colors, control_modes, enable_control):
    return connect_arm(arm, fields, URs, colors, control_modes, enable_control)


def freedrive_fun(arm, fields, URs, colors, control_modes):
    return toggle_freedrive(arm, fields, URs, colors, control_modes)


def gripper_fun(arm, fields, URs, colors):
    return toggle_gripper(arm, URs)


def home_fun(arm, fields, URs, colors, homes, control_modes, pos=None):
    return home_arm(arm, fields, URs, colors, homes, control_modes, pos=pos)


def emergency_stop(arm, fields, URs, colors, control_modes):
    return controller_emergency_stop(arm, fields, URs, colors, control_modes)


def invert_fun(arms, fields, control_modes):
    return invert_space_mouse(arms, fields, control_modes)


def ft_home(arm, URs, ros_data):
    return controller_ft_home(arm, URs, ros_data)
