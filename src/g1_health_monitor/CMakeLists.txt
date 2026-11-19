# Author: 김명준 (Kim Myeongjun), IIC 연구실
cmake_minimum_required(VERSION 3.10)
project(kmj_g1_health_monitor CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# unitree_sdk2는 /opt/unitree_robotics 에 설치되어 있어야 함 (CMAKE_PREFIX_PATH)
find_package(unitree_sdk2 REQUIRED)

add_executable(g1_health_monitor g1_health_monitor.cpp)
target_link_libraries(g1_health_monitor unitree_sdk2)
