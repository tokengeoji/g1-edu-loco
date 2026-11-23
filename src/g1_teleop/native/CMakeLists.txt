# Author: Codex (IIC)
cmake_minimum_required(VERSION 3.16)
project(g1_loco_binding LANGUAGES CXX)

find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(unitree_sdk2 REQUIRED)

Python3_add_library(_g1_loco MODULE loco_client.cpp)
target_compile_features(_g1_loco PRIVATE cxx_std_17)
target_link_libraries(_g1_loco PRIVATE unitree_sdk2)
# The ROS overlay also provides libddsc.so.0. Load the matching SDK libraries
# for this extension, including the transitive dependencies of libddscxx.
get_target_property(sdk_ddsc ddsc IMPORTED_LOCATION)
get_filename_component(sdk_lib_dir "${sdk_ddsc}" DIRECTORY)
target_link_options(_g1_loco PRIVATE "LINKER:--disable-new-dtags")
set_target_properties(_g1_loco PROPERTIES BUILD_RPATH "${sdk_lib_dir}" INSTALL_RPATH "${sdk_lib_dir}")

install(TARGETS _g1_loco LIBRARY DESTINATION .)
